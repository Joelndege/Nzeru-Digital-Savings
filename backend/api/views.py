import json
import logging
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from rest_framework import viewsets, permissions, status, generics, serializers
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import SimpleRateThrottle
from django.contrib.auth.models import User
from django.db import transaction as db_transaction
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from decimal import Decimal, InvalidOperation

from .models import (
    UserProfile, SavingsPlan, Transaction, Loan,
    LoanPayment, Penalty, InterestDistribution, Notification,
    IJCGroup, IJCMember, IJCTransaction, IJCAuditLog
)
from .serializers import (
    RegisterSerializer, UserSerializer, UserProfileSerializer,
    SavingsPlanSerializer, TransactionSerializer, LoanSerializer,
    LoanPaymentSerializer, PenaltySerializer, InterestDistributionSerializer,
    NotificationSerializer, IJCGroupSerializer, IJCMemberSerializer,
    IJCTransactionSerializer
)

logger = logging.getLogger(__name__)

FINANCIAL_KEYWORDS = re.compile(
    r'\b(sav(?:e|ing|ings)|balance|loan|credit|deposit|withdraw(?:al)?|'
    r'penalt(?:y|ies)|transaction|financial|money|budget|interest|'
    r'plan|repay(?:ment)?|eligible|eligibility|score)\b',
    re.IGNORECASE,
)

ECONOMIC_KEYWORDS = re.compile(
    r'\b(econom(?:y|ic|ics)|inflation|price(?:s)?|cost of living|'
    r'exchange rate|currency|devalu(?:e|ation)|gdp|growth|interest rate|'
    r'central bank|kwacha|macro(?:economics)?)\b',
    re.IGNORECASE,
)


class AssistantChatThrottle(SimpleRateThrottle):
    scope = 'assistant_chat'
    rate = '10/hour'

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': request.user.pk,
        }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([AssistantChatThrottle])
def assistant_chat(request):
    message = request.data.get('message')
    history = request.data.get('history', [])
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        return Response(
            {'detail': 'Message must contain 1 to 2000 characters.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not isinstance(history, list) or len(history) > 12:
        return Response(
            {'detail': 'Conversation history must contain at most 12 messages.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    safe_history = []
    for item in history:
        if not isinstance(item, dict):
            return Response({'detail': 'Invalid conversation history.'}, status=400)
        role = item.get('role')
        content = item.get('content')
        if role not in ('user', 'assistant') or not isinstance(content, str):
            return Response({'detail': 'Invalid conversation history.'}, status=400)
        safe_history.append({'role': role, 'content': content[:2000]})

    api_key = settings.AI_API_KEY
    conversation_text = ' '.join(
        [message] + [item['content'] for item in safe_history[-4:]]
    )
    financial_context = _assistant_financial_context(request.user) if FINANCIAL_KEYWORDS.search(conversation_text) else None
    economic_context = _assistant_economic_context() if ECONOMIC_KEYWORDS.search(conversation_text) else None

    if not api_key:
        return Response(
            {
                'reply': _assistant_fallback_reply(
                    request.user, message, safe_history, financial_context,
                    economic_context,
                )
            },
            status=status.HTTP_200_OK,
        )

    system_prompt = (
        'You are Nzeru Finance Coach, a warm, practical financial education '
        'assistant for people in Malawi. Focus first on budgeting, saving, '
        'responsible borrowing, financial wellbeing, and helping users understand '
        'the Nzeru app. Give clear, actionable answers in plain language. Explain '
        'relevant Nzeru savings or loan features naturally when they can help; '
        'never pressure users to buy, borrow, or deposit money, and never invent '
        'product terms, rates, fees, or guarantees. For account-specific questions, '
        'use only the supplied private Nzeru account snapshot. Never invent '
        'balances, transactions, eligibility, or actions. For general questions, '
        'answer directly and briefly, then offer finance help only when it fits. '
        'Treat financial guidance as educational, not a guarantee or professional '
        'financial advice. Never request bank passwords, PINs, verification codes, '
        'or payment credentials.'
    )
    if financial_context is not None:
        system_prompt += '\nAccount snapshot (private; use only for this user): ' + json.dumps(
            financial_context, separators=(',', ':')
        )
    if economic_context is not None:
        system_prompt += (
            '\nMalawi economic data snapshot (use only these dated figures for '
            'economic facts; name the source and observation year, and do not '
            'describe it as real-time): ' + json.dumps(
                economic_context, separators=(',', ':')
            )
        )

    payload = {
        'model': settings.AI_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            *safe_history,
            {'role': 'user', 'content': message.strip()},
        ],
        'temperature': 0.4,
        'max_tokens': 500,
    }
    provider_headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    if api_key:
        provider_headers['Authorization'] = f'Bearer {api_key}'

    provider_request = Request(
        f'{settings.AI_API_BASE_URL}/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers=provider_headers,
        method='POST',
    )

    try:
        with urlopen(provider_request, timeout=30) as response:
            provider_data = json.loads(response.read().decode('utf-8'))
    except HTTPError as error:
        logger.warning('AI provider returned HTTP %s', error.code)
        return Response(
            {
                'reply': _assistant_fallback_reply(
                    request.user, message, safe_history, financial_context,
                    economic_context,
                )
            },
            status=status.HTTP_200_OK,
        )
    except (URLError, TimeoutError, OSError, ValueError):
        logger.exception('AI provider request failed')
        return Response(
            {
                'reply': _assistant_fallback_reply(
                    request.user, message, safe_history, financial_context,
                    economic_context,
                )
            },
            status=status.HTTP_200_OK,
        )

    choices = provider_data.get('choices', [])
    reply = (
        choices[0].get('message', {}).get('content')
        if choices and isinstance(choices[0], dict)
        else None
    )
    if not isinstance(reply, str) or not reply.strip():
        return Response(
            {
                'reply': _assistant_fallback_reply(
                    request.user, message, safe_history, financial_context,
                    economic_context,
                )
            },
            status=status.HTTP_200_OK,
        )
    return Response({'reply': reply.strip()})


def _assistant_fallback_reply(
    user, message, safe_history=None, financial_context=None,
    economic_context=None,
):
    text = (message or '').lower()
    if financial_context is None and FINANCIAL_KEYWORDS.search(' '.join([message] + [item.get('content', '') for item in (safe_history or [])[-4:]])):
        financial_context = _assistant_financial_context(user)
    if economic_context is None and ECONOMIC_KEYWORDS.search(
        ' '.join([message] + [item.get('content', '') for item in (safe_history or [])[-4:]])
    ):
        economic_context = _assistant_economic_context()

    if economic_context:
        observations = economic_context.get('latest_indicators', [])
        if observations:
            figures = '; '.join(
                f"{item['name']}: {item['value']} {item['unit']} ({item['year']})"
                for item in observations[:4]
            )
            return (
                f"The latest Malawi figures in the local dataset are {figures}. "
                f"Source: {economic_context['source']}. These are dated economic "
                'indicators, not real-time prices or personalised financial advice.'
            )
        return (
            'The Malawi economics dataset has no usable observations yet. '
            'Ask an administrator to refresh it before relying on economic answers.'
        )

    if financial_context:
        savings_balance = Decimal(str(financial_context.get('savings_balance', 0)))
        tracked_savings = Decimal(str(financial_context.get('tracked_savings_balance', 0)))
        currency = financial_context.get('currency', 'MWK')
        active_plan_count = financial_context.get('active_plan_count', 0)
        active_loan = financial_context.get('has_pending_or_active_loan', False)
        maximum_loan = Decimal(str(financial_context.get('maximum_loan_by_current_rule', 0)))

        if any(term in text for term in ['savings', 'save', 'balance']):
            if tracked_savings > 0:
                return (
                    f'Your tracked savings are {currency} {tracked_savings:,.2f}, '
                    f'with an overall balance of {currency} {savings_balance:,.2f}. '
                    f'You currently have {active_plan_count} active savings plan(s), so the best next step is '
                    'to keep contributing consistently and review any recent withdrawals or penalties before you change your plan.'
                )
            return (
                'Your savings balance is currently low, which gives you room to start a structured plan. '
                'Consider setting one recurring deposit and aiming for a small weekly contribution to build momentum.'
            )

        if any(term in text for term in ['loan', 'borrow', 'credit', 'eligible']):
            if active_loan:
                return (
                    'You already have loan activity in progress, so the safest approach is to keep repayments on time and avoid taking on extra borrowing until your balance is more stable.'
                )
            return (
                f'Based on your tracked savings, the current rule suggests a maximum loan of about {currency} {maximum_loan:,.2f}. '
                'That is a guideline, not a promise, so use it as a planning limit and keep your cash flow comfortable before borrowing.'
            )

        if any(term in text for term in ['next week', 'week', 'plan', 'today']):
            return (
                'This week, focus on three simple actions: check your recent transactions, keep your safest savings contribution on schedule, and avoid any new spending that could reduce your balance.'
            )

        if any(term in text for term in ['why', 'change', 'balance']):
            return (
                'Balance changes usually come from deposits, withdrawals, interest rewards, penalties, or transfers between savings plans. Review your recent transaction list to see which category caused the movement.'
            )

    if any(term in text for term in ['savings', 'save', 'balance']):
        return (
            'For savings, the best habit is to keep a recurring contribution, protect your emergency cushion, and review your recent activity before making larger withdrawals.'
        )
    if any(term in text for term in ['loan', 'borrow', 'credit', 'eligible']):
        return (
            'For borrowing, start by checking your repayment capacity, keep your total debt manageable, and only borrow what you can comfortably repay without stressing your budget.'
        )
    if any(term in text for term in ['next week', 'week', 'plan', 'today']):
        return (
            'A simple plan for this week is to review your spending, protect one recurring savings transfer, and avoid any unnecessary fees or late payments.'
        )
    return (
        'I can help with personal finance basics, savings habits, and app guidance. Try asking about your savings balance, a loan estimate, or what to focus on this week.'
    )


def _assistant_economic_context():
    dataset_path = Path(settings.ECONOMIC_DATASET_PATH)
    try:
        with dataset_path.open(encoding='utf-8') as dataset_file:
            dataset = json.load(dataset_file)
    except (OSError, ValueError):
        logger.warning('Economic dataset is unavailable at %s', dataset_path)
        return None

    if not isinstance(dataset, dict) or not isinstance(dataset.get('indicators'), list):
        logger.warning('Economic dataset has an invalid format at %s', dataset_path)
        return None

    latest_indicators = []
    for indicator in dataset['indicators']:
        if not isinstance(indicator, dict):
            continue
        observations = indicator.get('observations', [])
        latest = next(
            (
                observation for observation in observations
                if isinstance(observation, dict) and observation.get('value') is not None
            ),
            None,
        )
        if latest is None:
            continue
        latest_indicators.append({
            'code': indicator.get('code'),
            'name': indicator.get('name'),
            'unit': indicator.get('unit', ''),
            'year': latest.get('year'),
            'value': latest.get('value'),
        })

    return {
        'country': dataset.get('country', 'Malawi'),
        'source': dataset.get('source', 'World Bank Indicators API'),
        'updated_at': dataset.get('updated_at'),
        'latest_indicators': latest_indicators,
    }


def _assistant_financial_context(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    active_plans = user.savings_plans.filter(is_active=True, is_trial=False)
    tracked_savings = sum(
        (plan.current_amount for plan in active_plans), start=0
    )
    active_loan = user.loans.filter(
        status__in=['PENDING', 'APPROVED', 'ACTIVE']
    ).exists()
    recent_transactions = list(
        user.transactions.filter(status='COMPLETED')
        .order_by('-timestamp')
        .values('type', 'amount')[:5]
    )
    return {
        'currency': profile.preferred_currency,
        'savings_balance': str(profile.savings_balance),
        'tracked_savings_balance': str(tracked_savings),
        'financial_score': profile.financial_score,
        'active_plan_count': active_plans.count(),
        'plans': [
            {
                'title': plan.title,
                'current_amount': str(plan.current_amount),
                'goal_amount': str(plan.goal_amount),
                'frequency': plan.frequency,
            }
            for plan in active_plans[:10]
        ],
        'recent_transactions': [
            {'type': item['type'], 'amount': str(item['amount'])}
            for item in recent_transactions
        ],
        'total_penalties': str(
            user.penalties.aggregate(total=Sum('amount'))['total'] or 0
        ),
        'has_pending_or_active_loan': active_loan,
        'maximum_loan_by_current_rule': str(tracked_savings * Decimal('0.4')),
        'loan_eligibility_rule': (
            'Maximum is 40% of tracked savings; user must have positive tracked '
            'savings and no pending or active loan.'
        ),
    }


# ─── Auth ───────────────────────────────────────────

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    """Return the current authenticated user's profile."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.recalculate_savings_balance()
    profile.recalculate_loan_balance()
    profile.calculate_financial_score()
    serializer = UserProfileSerializer(profile)
    return Response(serializer.data)


# ─── Dashboard Summary (single-call endpoint) ───────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    """
    Returns all data needed for the dashboard in one API call.
    Reduces round-trips and keeps the UI in sync.
    """
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Ensure balances are up to date
    profile.recalculate_savings_balance()
    profile.recalculate_loan_balance()
    profile.calculate_financial_score()

    active_plans = SavingsPlan.objects.filter(user=user, is_active=True)
    trial_plans = active_plans.filter(is_trial=True)
    secret_plans = active_plans.filter(is_secret=True)
    normal_plans = active_plans.filter(is_secret=False, is_trial=False)

    active_loans = Loan.objects.filter(
        user=user, status__in=['APPROVED', 'ACTIVE']
    )
    active_loan_balance = sum(l.remaining_balance for l in active_loans)
    tracked_savings = sum(p.current_amount for p in active_plans)

    recent_txns = Transaction.objects.filter(user=user).order_by('-timestamp')[:10]
    unread_count = Notification.objects.filter(user=user, is_read=False).count()
    total_penalties = Penalty.objects.filter(user=user).aggregate(Sum('amount'))['amount__sum'] or 0
    trial_penalties = Penalty.objects.filter(
        user=user,
        plan__is_trial=True,
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    return Response({
        'user': {
            'id': str(user.id),
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'name': f"{user.first_name} {user.last_name}".strip() or user.username,
            'phone': profile.phone,
            'savings_balance': float(profile.savings_balance),
            'tracked_savings_balance': float(tracked_savings),
            'credit_balance': float(profile.loan_balance),
            'loan_balance': float(profile.loan_balance),
            'financial_score': profile.financial_score,
            'settings': profile.settings_payload(),
        },
        'savings_balance': float(profile.savings_balance),
        'tracked_savings_balance': float(tracked_savings),
        'real_savings_balance': float(profile.savings_balance),
        'total_savings': float(tracked_savings),
        'credit_balance': float(profile.loan_balance),
        'loan_balance': float(profile.loan_balance),
        'financial_score': profile.financial_score,
        'active_credit_balance': float(active_loan_balance),
        'active_loan_balance': float(active_loan_balance),
        'active_plans': normal_plans.count(),
        'trial_plans': trial_plans.count(),
        'trial_savings_balance': float(sum(p.current_amount for p in trial_plans)),
        'secret_savings_count': secret_plans.count(),
        'secret_savings_balance': float(
            sum(p.current_amount for p in secret_plans)
        ),
        'total_penalties': float(total_penalties),
        'trial_penalties': float(trial_penalties),
        'recent_transactions': TransactionSerializer(recent_txns, many=True).data,
        'plans': SavingsPlanSerializer(active_plans, many=True).data,
        'active_credit': LoanSerializer(active_loans.first()).data if active_loans.exists() else None,
        'unread_notifications': unread_count,
    })


# ─── User Profile ──────────────────────────────────

class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    @action(detail=False, methods=['post'])
    def recalculate(self, request):
        """Recalculate balances and score."""
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.recalculate_savings_balance()
        profile.recalculate_loan_balance()
        profile.calculate_financial_score()
        return Response(UserProfileSerializer(profile).data)

    @action(detail=False, methods=['patch'])
    def settings(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        payload = request.data
        simple_fields = [
            'preferred_theme',
            'preferred_language',
            'preferred_currency',
            'notifications_enabled',
            'transaction_alerts',
            'two_factor_enabled',
            'biometric_login_enabled',
            'auto_save_enabled',
            'credit_usage_preference',
            'app_feedback',
        ]
        for field in simple_fields:
            if field in payload:
                setattr(profile, field, payload[field])

        if 'payment_methods' in payload:
            methods = payload.get('payment_methods') or []
            if isinstance(methods, list):
                profile.payment_methods = ','.join(
                    str(item).strip() for item in methods if str(item).strip()
                )
            else:
                profile.payment_methods = str(methods)

        if 'default_savings_plan_id' in payload:
            plan_id = payload.get('default_savings_plan_id')
            profile.default_savings_plan = SavingsPlan.objects.filter(
                user=request.user,
                id=plan_id,
            ).first() if plan_id else None

        profile.save()
        return Response(profile.settings_payload())

    @action(detail=False, methods=['post'])
    def change_password(self, request):
        user = request.user
        current_password = request.data.get('current_password', '')
        new_password = request.data.get('new_password', '')
        if not user.check_password(current_password):
            raise serializers.ValidationError({
                'current_password': 'Current password is incorrect.'
            })
        if not new_password:
            raise serializers.ValidationError({
                'new_password': 'New password is required.'
            })
        user.set_password(new_password)
        user.save(update_fields=['password'])
        return Response({'status': 'password_updated'})


# ─── Savings Plans ─────────────────────────────────

class SavingsPlanViewSet(viewsets.ModelViewSet):
    queryset = SavingsPlan.objects.all()
    serializer_class = SavingsPlanSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = self.queryset.filter(user=self.request.user).order_by('-start_date')
        # Allow ?secret=true / ?secret=false filtering
        secret = self.request.query_params.get('secret')
        if secret is not None:
            qs = qs.filter(is_secret=secret.lower() == 'true')
        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'])
    def simulate_penalty(self, request, pk=None):
        plan = self.get_object()
        amount = Decimal(str(request.data.get('amount', '250')))
        penalty = Penalty.objects.create(
            user=request.user,
            plan=plan,
            amount=amount,
            penalty_type='MONETARY',
            reason=request.data.get('reason') or 'Simulated penalty for testing.',
            is_applied=True,
        )
        if plan.current_amount > 0:
            plan.current_amount = max(Decimal('0'), plan.current_amount - amount)
            plan.save(update_fields=['current_amount'])
        if not plan.is_trial:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            profile.recalculate_savings_balance()
        return Response(PenaltySerializer(penalty).data, status=status.HTTP_201_CREATED)


# ─── Transactions (Deposits) ──────────────────────

class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _parse_decimal(value, field_name='amount'):
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise serializers.ValidationError({
                field_name: 'Enter a valid amount.'
            })

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user).order_by('-timestamp')

    def create(self, request, *args, **kwargs):
        if request.data.get('type') == 'WITHDRAWAL':
            has_credit = request.user.loans.filter(
                status__in=['PENDING', 'APPROVED', 'ACTIVE']
            ).exists()
            if has_credit:
                Notification.objects.create(
                    user=request.user,
                    title='Withdrawal unavailable',
                    message='Withdrawal unavailable while outstanding debt exists.',
                    type='DEBT_ALERT',
                )
                return Response(
                    {
                        'detail': 'Withdrawal unavailable while outstanding debt exists.'
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            plan_id = request.data.get('plan')
            if plan_id:
                plan = SavingsPlan.objects.filter(user=request.user, id=plan_id).first()
                if not plan:
                    return Response(
                        {'detail': 'Savings plan not found.'},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                amount = self._parse_decimal(request.data.get('amount', '0'))
                if amount <= 0:
                    raise serializers.ValidationError({
                        'amount': 'Withdrawal amount must be greater than zero.'
                    })
                if amount > plan.current_amount:
                    raise serializers.ValidationError({
                        'amount': 'Withdrawal amount exceeds current savings.'
                    })
                if plan.goal_lock_enabled and plan.current_amount < plan.goal_amount:
                    Notification.objects.create(
                        user=request.user,
                        title='Withdrawal locked',
                        message=f'Complete your savings target of MK {plan.goal_amount} to unlock withdrawals.',
                        type='SAVINGS_REMINDER',
                    )
                    return Response(
                        {
                            'detail': f'You cannot withdraw funds until your target of MK {plan.goal_amount} is reached.',
                            'lock_status': plan.lock_status,
                            'target_amount': plan.goal_amount,
                            'current_amount': plan.current_amount,
                            'remaining_amount': plan.goal_lock_remaining_amount,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if not plan.is_mature:
                    Notification.objects.create(
                        user=request.user,
                        title='Savings still locked',
                        message='Withdrawals are locked until your savings maturity date is reached.',
                        type='SAVINGS_REMINDER',
                    )
                    return Response(
                        {
                            'detail': 'Withdrawals are locked until your savings maturity date is reached.',
                            'maturity_date': plan.end_date,
                            'days_remaining': plan.days_until_maturity,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        txn = serializer.save(user=self.request.user)
        if txn.plan and txn.type == 'DEPOSIT':
            plan = txn.plan
            plan.current_amount += txn.amount
            plan.save(update_fields=['current_amount'])
            Notification.objects.create(
                user=self.request.user,
                title='Deposit received',
                message=f'MK {txn.amount} was added to {plan.title}.',
                type='DEPOSIT_RECEIVED',
            )
            if plan.goal_amount > 0 and plan.current_amount >= plan.goal_amount:
                Notification.objects.create(
                    user=self.request.user,
                    title='Savings goal achieved',
                    message=f'{plan.title} has reached its savings goal.',
                    type='GOAL_ACHIEVED',
                )
                if plan.goal_lock_enabled:
                    Notification.objects.create(
                        user=self.request.user,
                        title='Withdrawal unlocked',
                        message=f'{plan.title} reached its goal. Withdrawals are now unlocked.',
                        type='WITHDRAWAL_UNLOCK',
                    )
        elif txn.plan and txn.type in ['WITHDRAWAL', 'PENALTY']:
            plan = txn.plan
            plan.current_amount = max(Decimal('0'), plan.current_amount - txn.amount)
            plan.save(update_fields=['current_amount'])

        if not (txn.plan and txn.plan.is_trial):
            profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
            profile.recalculate_savings_balance()


# ─── Penalties ─────────────────────────────────────

class PenaltyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Penalty.objects.all()
    serializer_class = PenaltySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user).order_by('-date')


# ─── Loans ─────────────────────────────────────────

class LoanViewSet(viewsets.ModelViewSet):
    queryset = Loan.objects.all()
    serializer_class = LoanSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        """Create a credit request with 40% tracked savings eligibility."""
        plan = serializer.validated_data.get('plan')
        amount = serializer.validated_data['amount']
        interest_rate = serializer.validated_data.get('interest_rate', Decimal('10'))
        tracked_savings = plan.current_amount if plan else sum(
            item.current_amount
            for item in SavingsPlan.objects.filter(user=self.request.user, is_active=True)
        )
        max_credit = Decimal(str(tracked_savings)) * Decimal('0.40')
        if amount > max_credit:
            raise serializers.ValidationError({
                'amount': 'Requested credit exceeds 40% of tracked savings.'
            })
        if self.request.user.loans.filter(status__in=['PENDING', 'APPROVED', 'ACTIVE']).exists():
            raise serializers.ValidationError({
                'detail': 'Only one outstanding credit request is allowed at a time.'
            })
        total = amount * (1 + interest_rate / 100)
        serializer.save(
            user=self.request.user,
            status='PENDING',
            remaining_balance=total,
        )


# ─── Loan Eligibility ─────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def loan_eligibility(request):
    """Check how much the user is eligible to access as credit (40% of tracked savings)."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.recalculate_savings_balance()
    plan_id = request.query_params.get('plan')
    selected_plan = SavingsPlan.objects.filter(user=request.user, id=plan_id).first() if plan_id else None
    tracked_savings = float(
        selected_plan.current_amount if selected_plan else sum(
            plan.current_amount
            for plan in SavingsPlan.objects.filter(user=request.user, is_active=True)
        )
    )
    max_loan = tracked_savings * 0.4
    has_active_loan = request.user.loans.filter(
        status__in=['PENDING', 'APPROVED', 'ACTIVE']
    ).exists()
    return Response({
        'savings_balance': float(profile.savings_balance),
        'tracked_savings_balance': tracked_savings,
        'selected_plan_id': str(selected_plan.id) if selected_plan else None,
        'max_loan_amount': max_loan,
        'has_active_loan': has_active_loan,
        'eligible': max_loan > 0 and not has_active_loan,
        'financial_score': profile.financial_score,
    })


# ─── Loan Payments ─────────────────────────────────

class LoanPaymentViewSet(viewsets.ModelViewSet):
    queryset = LoanPayment.objects.all()
    serializer_class = LoanPaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(loan__user=self.request.user).order_by('-payment_date')

    def perform_create(self, serializer):
        loan_id = self.request.data.get('loan')
        try:
            loan = Loan.objects.get(
                id=loan_id, user=self.request.user,
                status__in=['APPROVED', 'ACTIVE']
            )
        except Loan.DoesNotExist:
            return

        amount = serializer.validated_data['amount_paid']
        new_remaining = max(Decimal('0'), loan.remaining_balance - amount)
        serializer.save(remaining_balance=new_remaining)

        loan.remaining_balance = new_remaining
        if new_remaining <= 0:
            loan.status = 'PAID'
            self._distribute_interest(loan)
        else:
            loan.status = 'ACTIVE'
        loan.save()

        profile, _ = UserProfile.objects.get_or_create(user=loan.user)
        profile.recalculate_loan_balance()

    def _distribute_interest(self, loan):
        """Split interest 50/50 between user savings and platform."""
        total_interest = loan.amount * loan.interest_rate / 100
        user_share = total_interest / 2
        platform_share = total_interest / 2

        InterestDistribution.objects.create(
            loan=loan,
            total_interest=total_interest,
            user_savings_share=user_share,
            platform_share=platform_share,
        )
        Transaction.objects.create(
            user=loan.user,
            plan=loan.plan,
            amount=user_share,
            type='INTEREST_REWARD',
            status='COMPLETED',
            description=f'Interest reward from Credit #{loan.id}',
        )
        if loan.plan:
            loan.plan.current_amount += user_share
            loan.plan.save(update_fields=['current_amount'])
        profile, _ = UserProfile.objects.get_or_create(user=loan.user)
        if not loan.is_trial:
            profile.recalculate_savings_balance()

        Notification.objects.create(
            user=loan.user,
            title='Credit Fully Repaid!',
            message=f'You earned MK {user_share} in interest rewards from your credit.',
            type='INTEREST_REWARD',
        )


# ─── Interest Distributions ───────────────────────

class InterestDistributionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = InterestDistribution.objects.all()
    serializer_class = InterestDistributionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(loan__user=self.request.user).order_by('-distributed_at')


# ─── Notifications ─────────────────────────────────

class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user).order_by('-created_at')

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return Response({'status': 'marked as read'})

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({'status': 'all marked as read'})


class IJCGroupViewSet(viewsets.ModelViewSet):
    queryset = IJCGroup.objects.all()
    serializer_class = IJCGroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(
            Q(owner=self.request.user) |
            Q(controller=self.request.user) |
            Q(members__user=self.request.user, members__status__in=['PENDING', 'APPROVED']),
            is_active=True,
        ).distinct().order_by('-created_at')

    def perform_create(self, serializer):
        group = serializer.save(owner=self.request.user)
        IJCMember.objects.create(
            group=group,
            user=self.request.user,
            role='USER',
            status='APPROVED',
            approved_at=timezone.now(),
        )
        IJCAuditLog.objects.create(
            group=group,
            actor=self.request.user,
            action='IJC_CREATED',
            metadata={
                'daily_limit': str(group.daily_limit),
                'weekly_limit': str(group.weekly_limit),
                'monthly_limit': str(group.monthly_limit),
                'reset_type': group.reset_type,
            },
        )

    def perform_update(self, serializer):
        group = self.get_object()
        self._require_controller(group)
        updated = serializer.save()
        Notification.objects.create(
            user=updated.owner,
            title='IJC policy updated',
            message=f'The spending policy for {updated.name} was updated.',
            type='IJC_POLICY_UPDATED',
        )
        IJCAuditLog.objects.create(
            group=updated,
            actor=self.request.user,
            action='IJC_POLICY_UPDATED',
            metadata={
                'daily_limit': str(updated.daily_limit),
                'weekly_limit': str(updated.weekly_limit),
                'monthly_limit': str(updated.monthly_limit),
                'reset_type': updated.reset_type,
                'allow_rollover': updated.allow_rollover,
            },
        )

    def destroy(self, request, *args, **kwargs):
        group = self.get_object()
        if request.user != group.owner:
            self._require_controller(group)
        group.is_active = False
        group.save(update_fields=['is_active'])
        IJCAuditLog.objects.create(
            group=group,
            actor=request.user,
            action='IJC_DEACTIVATED',
            metadata={},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _membership(self, group):
        return group.members.filter(user=self.request.user).first()

    def _require_controller(self, group):
        membership = self._membership(group)
        if (
            not membership or
            membership.role != 'CONTROLLER' or
            membership.status != 'APPROVED' or
            group.controller_id != self.request.user.id
        ):
            raise serializers.ValidationError({
                'detail': 'Only the IJC controller can perform this action.'
            })
        return membership

    def _require_approved_member(self, group):
        membership = self._membership(group)
        if not membership or membership.status != 'APPROVED':
            raise serializers.ValidationError({
                'detail': 'Only linked IJC users can perform this action.'
            })
        return membership

    def _require_wallet_user(self, group):
        membership = self._membership(group)
        if (
            not membership or
            membership.status != 'APPROVED' or
            membership.role not in ['USER', 'OWNER'] or
            group.owner_id != self.request.user.id
        ):
            raise serializers.ValidationError({
                'detail': 'Only the IJC user can withdraw from this account.'
            })
        return membership

    @staticmethod
    def _parse_amount(value, field_name='amount'):
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise serializers.ValidationError({
                field_name: 'Enter a valid amount.'
            })

    def _validate_withdrawal_limits(self, group, amount):
        checks = [
            ('daily', group.daily_limit, group.daily_spent, 'Daily withdrawal limit reached. Try again tomorrow.'),
            ('weekly', group.weekly_limit, group.weekly_spent, 'Weekly withdrawal limit reached.'),
            ('monthly', group.monthly_limit, group.monthly_spent, 'Monthly withdrawal limit reached.'),
        ]
        for period, limit, spent, message in checks:
            if limit > 0 and spent + amount > limit:
                Notification.objects.create(
                    user=group.owner,
                    title='IJC limit reached',
                    message=message,
                    type='IJC_LIMIT_REACHED',
                )
                if group.controller:
                    Notification.objects.create(
                        user=group.controller,
                        title='IJC overspending attempt',
                        message=f'{group.owner.get_full_name() or group.owner.username} attempted to withdraw MK {amount} from {group.name}.',
                        type='IJC_LIMIT_ATTEMPT',
                    )
                IJCAuditLog.objects.create(
                    group=group,
                    actor=self.request.user,
                    action='IJC_WITHDRAWAL_BLOCKED',
                    metadata={
                        'period': period,
                        'amount': str(amount),
                        'limit': str(limit),
                        'spent': str(spent),
                    },
                )
                raise serializers.ValidationError({
                    'detail': message,
                    'period': period,
                    'limit': str(limit),
                    'spent': str(spent),
                })

    @action(detail=False, methods=['post'])
    def join(self, request):
        code = str(request.data.get('code', '')).strip().upper()
        if not code:
            raise serializers.ValidationError({'code': 'Pocket ID or join code is required.'})
        group = IJCGroup.objects.filter(ijc_id=code).first() or IJCGroup.objects.filter(join_code=code).first()
        if not group:
            return Response({'detail': 'Pocket not found.'}, status=status.HTTP_404_NOT_FOUND)
        if request.user == group.owner:
            return Response(IJCGroupSerializer(group, context={'request': request}).data)
        if group.pocket_type == 'SELF':
            return Response({'detail': 'Self pockets cannot be joined.'}, status=status.HTTP_400_BAD_REQUEST)
        if group.controller and group.controller_id != request.user.id:
            return Response({'detail': 'This pocket already has a controller.'}, status=status.HTTP_400_BAD_REQUEST)

        total_amount_input = request.data.get('total_amount')
        release_amount_input = request.data.get('release_amount')
        cash_out_policy = request.data.get('cash_out_policy')
        custom_interval_days = request.data.get('custom_interval_days')

        with db_transaction.atomic():
            membership, created = IJCMember.objects.get_or_create(
                group=group,
                user=request.user,
                defaults={'role': 'CONTROLLER', 'status': 'APPROVED', 'approved_at': timezone.now()},
            )
            membership.role = 'CONTROLLER'
            membership.status = 'APPROVED'
            membership.approved_at = timezone.now()
            membership.save(update_fields=['role', 'status', 'approved_at'])
            group.controller = request.user
            if total_amount_input is not None:
                group.total_amount = self._parse_amount(total_amount_input, 'total_amount')
            if release_amount_input is not None:
                group.release_amount = self._parse_amount(release_amount_input, 'release_amount')
            if cash_out_policy in ['DAILY', 'WEEKLY', 'MONTHLY', 'CUSTOM']:
                group.cash_out_policy = cash_out_policy
            if custom_interval_days is not None:
                try:
                    group.custom_interval_days = int(custom_interval_days)
                except (TypeError, ValueError):
                    raise serializers.ValidationError({'custom_interval_days': 'Enter a valid number.'})
            group.save(update_fields=['controller', 'total_amount', 'release_amount', 'cash_out_policy', 'custom_interval_days'])

        Notification.objects.create(
            user=group.owner,
            title='Controller linked',
            message=f'{request.user.get_full_name() or request.user.username} is now controller for {group.name}.',
            type='IJC_MEMBER_JOINED',
        )
        IJCAuditLog.objects.create(
            group=group,
            actor=request.user,
            action='POCKET_CONTROLLER_LINKED',
            metadata={'created': created},
        )
        return Response(IJCGroupSerializer(group, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def approve_member(self, request, pk=None):
        group = self.get_object()
        self._require_controller(group)
        member_id = request.data.get('member_id')
        member = group.members.filter(id=member_id).first()
        if not member:
            return Response({'detail': 'Member request not found.'}, status=status.HTTP_404_NOT_FOUND)
        member.status = 'APPROVED'
        member.approved_at = timezone.now()
        member.save(update_fields=['status', 'approved_at'])
        Notification.objects.create(
            user=member.user,
            title='IJC membership approved',
            message=f'You can now contribute to {group.name}.',
            type='IJC_MEMBER_JOINED',
        )
        IJCAuditLog.objects.create(
            group=group,
            actor=request.user,
            action='IJC_MEMBER_APPROVED',
            metadata={'member_id': member.id},
        )
        return Response(IJCMemberSerializer(member).data)

    @action(detail=True, methods=['post'])
    def deposit(self, request, pk=None):
        group = self.get_object()
        membership = self._require_approved_member(group)
        amount = self._parse_amount(request.data.get('amount', '0'))
        if amount <= 0:
            raise serializers.ValidationError({'amount': 'Deposit amount must be greater than zero.'})
        reference = request.data.get('client_reference') or None
        with db_transaction.atomic():
            group = IJCGroup.objects.select_for_update().get(pk=group.pk)
            # Support parent-provided configuration on initial deposit
            total_amount_input = request.data.get('total_amount')
            release_amount_input = request.data.get('release_amount')
            cash_out_policy = request.data.get('cash_out_policy')
            if total_amount_input:
                total_amt = self._parse_amount(total_amount_input, 'total_amount')
                group.total_amount = total_amt
            if release_amount_input:
                rel_amt = self._parse_amount(release_amount_input, 'release_amount')
                group.release_amount = rel_amt
            if cash_out_policy in ['DAILY', 'WEEKLY', 'MONTHLY', 'CUSTOM']:
                group.cash_out_policy = cash_out_policy
            if reference:
                existing = group.transactions.filter(client_reference=reference).first()
                if existing:
                    return Response(IJCTransactionSerializer(existing).data, status=status.HTTP_200_OK)
            txn = IJCTransaction.objects.create(
                group=group,
                user=request.user,
                amount=amount,
                type='DEPOSIT',
                description=request.data.get('description', ''),
                client_reference=reference,
            )
            group.balance += amount
            # Keep legacy goal_amount in sync for backwards compatibility
            group.goal_amount += amount
            if total_amount_input:
                group.total_amount = self._parse_amount(total_amount_input, 'total_amount')
            else:
                if group.total_amount > 0:
                    group.total_amount += amount
                else:
                    group.total_amount = amount
            group.save(update_fields=['balance', 'goal_amount', 'total_amount', 'release_amount', 'cash_out_policy'])
            membership.total_contributed += amount
            membership.save(update_fields=['total_contributed'])
        Notification.objects.create(
            user=group.owner if request.user != group.owner else group.controller or group.owner,
            title='IJC deposit received',
            message=f'MK {amount} was deposited into {group.name}.',
            type='IJC_DEPOSIT_RECEIVED',
        )
        IJCAuditLog.objects.create(
            group=group,
            actor=request.user,
            action='IJC_DEPOSIT_CREATED',
            metadata={'amount': str(amount), 'note': request.data.get('description', '')},
        )
        return Response(IJCTransactionSerializer(txn).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def withdraw(self, request, pk=None):
        group = self.get_object()
        self._require_wallet_user(group)
        if group.is_paused:
            raise serializers.ValidationError({'detail': 'This credit is paused.'})
        amount = self._parse_amount(request.data.get('amount', '0'))
        if amount <= 0:
            raise serializers.ValidationError({'amount': 'Withdrawal amount must be greater than zero.'})
        if amount > group.available_balance:
            raise serializers.ValidationError({'amount': 'Withdrawal exceeds available balance.'})
        reference = request.data.get('client_reference') or None
        with db_transaction.atomic():
            group = IJCGroup.objects.select_for_update().get(pk=group.pk)
            if reference:
                existing = group.transactions.filter(client_reference=reference).first()
                if existing:
                    return Response(IJCTransactionSerializer(existing).data, status=status.HTTP_200_OK)
            txn = IJCTransaction.objects.create(
                group=group,
                user=request.user,
                amount=amount,
                type='WITHDRAWAL',
                description=request.data.get('description', ''),
                client_reference=reference,
            )
            group.balance -= amount
            group.last_cash_out_at = timezone.now()
            group.save(update_fields=['balance', 'last_cash_out_at'])
        recipients = [group.owner]
        if group.controller:
            recipients.append(group.controller)
        for user in set(recipients):
            Notification.objects.create(
                user=user,
                title='IJC withdrawal completed',
                message=f'MK {amount} was withdrawn from {group.name}.',
                type='IJC_WITHDRAWAL_COMPLETED',
            )
        IJCAuditLog.objects.create(
            group=group,
            actor=request.user,
            action='IJC_WITHDRAWAL_CREATED',
            metadata={'amount': str(amount)},
        )
        return Response(IJCTransactionSerializer(txn).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        group = self.get_object()
        self._require_controller(group)
        group.is_paused = True
        group.paused_at = timezone.now()
        group.save(update_fields=['is_paused', 'paused_at'])
        return Response(IJCGroupSerializer(group, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        group = self.get_object()
        self._require_controller(group)
        group.is_paused = False
        group.pause_duration_seconds = 0
        group.paused_at = None
        group.save(update_fields=['is_paused', 'pause_duration_seconds', 'paused_at'])
        return Response(IJCGroupSerializer(group, context={'request': request}).data)


# ─── Reports ───────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def financial_report(request):
    """Generate financial summary report for the authenticated user."""
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.recalculate_savings_balance()
    profile.recalculate_loan_balance()
    profile.calculate_financial_score()

    monthly_savings = (
        Transaction.objects.filter(user=user, type='DEPOSIT', status='COMPLETED')
        .annotate(month=TruncMonth('timestamp'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    loans = Loan.objects.filter(user=user)
    total_loans_taken = loans.count()
    total_borrowed = loans.aggregate(total=Sum('amount'))['total'] or 0
    total_repaid = LoanPayment.objects.filter(loan__user=user).aggregate(
        total=Sum('amount_paid')
    )['total'] or 0

    total_penalties = Penalty.objects.filter(user=user).aggregate(
        total=Sum('amount')
    )['total'] or 0
    penalty_count = Penalty.objects.filter(user=user).count()
    tracked_savings = sum(
        plan.current_amount
        for plan in SavingsPlan.objects.filter(user=user, is_active=True)
    )
    trial_savings = sum(
        plan.current_amount
        for plan in SavingsPlan.objects.filter(user=user, is_active=True, is_trial=True)
    )

    return Response({
        'savings_balance': float(profile.savings_balance),
        'tracked_savings_balance': float(tracked_savings),
        'trial_savings_balance': float(trial_savings),
        'credit_balance': float(profile.loan_balance),
        'loan_balance': float(profile.loan_balance),
        'financial_score': profile.financial_score,
        'monthly_savings': [
            {'month': entry['month'].strftime('%Y-%m'), 'total': float(entry['total'])}
            for entry in monthly_savings
        ],
        'credits': {
            'total_taken': total_loans_taken,
            'total_borrowed': float(total_borrowed),
            'total_repaid': float(total_repaid),
        },
        'loans': {
            'total_taken': total_loans_taken,
            'total_borrowed': float(total_borrowed),
            'total_repaid': float(total_repaid),
        },
        'penalties': {
            'total_amount': float(total_penalties),
            'count': penalty_count,
        },
    })
