import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

import '../../config/app_colors.dart';
import '../../models/savings_plan.dart';
import '../../models/savings_transaction.dart';
import '../../providers/auth_provider.dart';
import '../../providers/savings_provider.dart';
import '../../widgets/dashboard_kit.dart';
import '../../widgets/app_button.dart';
import '../../widgets/mobile_money_payment_sheet.dart';

class DepositScreenArgs {
  final String? planId;
  final double? initialAmount;
  final bool lockPlan;
  final bool requireDeposit;
  final String? planTitle;

  const DepositScreenArgs({
    this.planId,
    this.initialAmount,
    this.lockPlan = false,
    this.requireDeposit = false,
    this.planTitle,
  });
}

class DepositScreen extends StatefulWidget {
  const DepositScreen({super.key});

  @override
  State<DepositScreen> createState() => _DepositScreenState();
}

class _DepositScreenState extends State<DepositScreen> {
  final _amountController = TextEditingController();
  String? _selectedPlanId;
  bool _isProcessing = false;
  bool _initializedFromArgs = false;

  @override
  void dispose() {
    _amountController.dispose();
    super.dispose();
  }

  DepositScreenArgs? _routeArgs(BuildContext context) {
    final raw = ModalRoute.of(context)?.settings.arguments;
    return raw is DepositScreenArgs ? raw : null;
  }

  @override
  Widget build(BuildContext context) {
    final savings = context.watch<SavingsProvider>();
    final args = _routeArgs(context);
    final activePlans = savings.plans.where((p) => p.isActive).toList();

    if (!_initializedFromArgs) {
      _initializedFromArgs = true;
      _selectedPlanId = args?.planId;
      if ((args?.initialAmount ?? 0) > 0) {
        _amountController.text = args!.initialAmount!.toStringAsFixed(2);
      }
    }

    SavingsPlan? lockedPlan;
    if (args?.planId != null) {
      for (final plan in activePlans) {
        if (plan.id == args!.planId) {
          lockedPlan = plan;
          break;
        }
      }
    }

    final displayedPlans =
        args?.lockPlan == true && lockedPlan != null ? [lockedPlan] : activePlans;

    return WillPopScope(
      onWillPop: () async {
        if (args?.requireDeposit == true) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'Make the first deposit to finish setting up this savings plan.',
              ),
            ),
          );
          return false;
        }
        return true;
      },
      child: Scaffold(
        backgroundColor: AppColors.background,
        appBar: AppBar(
          title: Text(
            'Make a deposit',
            style: GoogleFonts.poppins(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: Colors.white,
            ),
          ),
          backgroundColor: AppColors.brandBlueDark,
          elevation: 0,
          automaticallyImplyLeading: args?.requireDeposit != true,
          leading: args?.requireDeposit == true
              ? null
              : IconButton(
                  icon: const Icon(Icons.arrow_back_ios, color: Colors.white),
                  onPressed: () => Navigator.pop(context),
                ),
        ),
        body: Stack(
          children: [
            const DashboardBackdrop(darkMode: false),
            SafeArea(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Center(
                      child: Container(
                        width: 76,
                        height: 76,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: AppColors.brandBlue,
                          boxShadow: [
                            BoxShadow(
                              color: AppColors.brandBlue.withValues(alpha: 0.2),
                              blurRadius: 18,
                              offset: const Offset(0, 8),
                            ),
                          ],
                        ),
                        child: const Icon(
                          Icons.savings_rounded,
                          color: Colors.white,
                          size: 36,
                        ),
                      ),
                    ).animate().scale(duration: 500.ms, curve: Curves.elasticOut),
                    const SizedBox(height: 14),
                    Center(
                      child: Text(
                        'Add money to your savings',
                        textAlign: TextAlign.center,
                        style: GoogleFonts.poppins(
                          fontSize: 20,
                          fontWeight: FontWeight.w700,
                          color: const Color(0xFF171717),
                        ),
                      ),
                    ),
                    const SizedBox(height: 5),
                    Center(
                      child: Text(
                        'Choose a plan and enter an amount to deposit.',
                        textAlign: TextAlign.center,
                        style: GoogleFonts.poppins(
                          fontSize: 12,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ),
                    if (args?.requireDeposit == true) ...[
                      const SizedBox(height: 22),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: AppColors.brandBlueLight,
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(
                            color: AppColors.brandBlue.withAlpha(60),
                          ),
                        ),
                        child: Text(
                          'Complete the first deposit for ${args?.planTitle ?? 'your new plan'} before leaving this setup.',
                          style: GoogleFonts.poppins(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: AppColors.brandBlueDark,
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(height: 30),
                    Text(
                      'SELECT SAVINGS PLAN',
                      style: GoogleFonts.poppins(
                        fontSize: 11,
                        color: AppColors.brandBlueDark,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1.2,
                      ),
                    ),
                    const SizedBox(height: 10),
                    ...displayedPlans.map((plan) {
                      final isSelected = _selectedPlanId == plan.id;
                      return GestureDetector(
                        onTap: args?.lockPlan == true
                            ? null
                            : () => setState(() => _selectedPlanId = plan.id),
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 200),
                          margin: const EdgeInsets.only(bottom: 10),
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: isSelected
                                ? AppColors.brandBlue
                                : Colors.white,
                            borderRadius: BorderRadius.circular(16),
                            border: Border.all(
                              color: isSelected
                                  ? AppColors.brandBlue
                                  : AppColors.border,
                              width: isSelected ? 1.5 : 1,
                            ),
                            boxShadow: isSelected
                                ? [
                                    BoxShadow(
                                      color: AppColors.brandBlue
                                          .withValues(alpha: 0.14),
                                      blurRadius: 14,
                                      offset: const Offset(0, 6),
                                    ),
                                  ]
                                : null,
                          ),
                          child: Row(
                            children: [
                              Icon(
                                Icons.savings_outlined,
                                color: isSelected
                                  ? Colors.white
                                  : AppColors.textMuted,
                                size: 20,
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Text(
                                  '${plan.title} - ${plan.frequencyLabel} - MK${plan.amountPerPeriod.toStringAsFixed(2)}/period',
                                  style: GoogleFonts.poppins(
                                    fontSize: 14,
                                    color: isSelected
                                      ? Colors.white
                                      : AppColors.textSecondary,
                                  ),
                                ),
                              ),
                              if (isSelected)
                                const Icon(
                                  Icons.check_circle,
                                  color: Colors.white,
                                  size: 20,
                                ),
                            ],
                          ),
                        ),
                      );
                    }),
                    const SizedBox(height: 28),
                    Text(
                      'DEPOSIT AMOUNT',
                      style: GoogleFonts.poppins(
                        fontSize: 11,
                        color: AppColors.brandBlueDark,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1.2,
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextFormField(
                      controller: _amountController,
                      keyboardType:
                          const TextInputType.numberWithOptions(decimal: true),
                      style: GoogleFonts.poppins(
                        fontSize: 32,
                        color: AppColors.brandBlue,
                        fontWeight: FontWeight.w700,
                      ),
                      decoration: InputDecoration(
                        filled: true,
                        fillColor: Colors.white,
                        hintText: '0.00',
                        hintStyle: GoogleFonts.poppins(
                          color: AppColors.textMuted,
                          fontSize: 32,
                        ),
                        prefixText: 'MK ',
                        prefixStyle: GoogleFonts.poppins(
                          fontSize: 32,
                          color: AppColors.brandBlue,
                          fontWeight: FontWeight.w700,
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 18,
                          vertical: 16,
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(16),
                          borderSide: const BorderSide(color: Color(0xFFE2D4D4)),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(16),
                          borderSide: const BorderSide(
                            color: AppColors.brandBlue,
                            width: 1.6,
                          ),
                        ),
                      ),
                    ).animate().fadeIn(delay: 200.ms),
                    const SizedBox(height: 40),
                    AppButton(
                      label: args?.requireDeposit == true
                          ? 'MAKE FIRST DEPOSIT'
                          : 'CONFIRM DEPOSIT',
                      icon: Icons.check_circle_outline,
                      isLoading: _isProcessing,
                      width: double.infinity,
                      color: AppColors.brandBlue,
                      onPressed: () async {
                        final amount = double.tryParse(_amountController.text);
                        if (amount == null || amount <= 0) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('Enter a valid amount')),
                          );
                          return;
                        }
                        if (_selectedPlanId == null) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('Select a savings plan')),
                          );
                          return;
                        }

                        final paymentChoice = await showMobileMoneyPaymentSheet(
                          context,
                          action: 'Deposit',
                          amount: amount,
                        );
                        if (paymentChoice == null || !context.mounted) return;

                        final auth = context.read<AuthProvider>();
                        setState(() => _isProcessing = true);
                        final navigator = Navigator.of(context);
                        final messenger = ScaffoldMessenger.of(context);

                        final success = await savings.addDeposit(
                          SavingsTransaction(
                            id: '',
                            userId: auth.user?.id ?? '',
                            planId: _selectedPlanId,
                            amount: amount,
                            date: DateTime.now(),
                            type: TransactionType.deposit,
                            description: args?.requireDeposit == true
                                ? 'Initial plan deposit · ${paymentChoice.providerName} (demo)'
                                : 'Manual deposit · ${paymentChoice.providerName} (demo)',
                          ),
                        );

                        if (!mounted) return;

                        setState(() => _isProcessing = false);
                        if (success) {
                          navigator.pop();
                          messenger.showSnackBar(
                            SnackBar(
                              content: Text(
                                'Deposited MK${amount.toStringAsFixed(2)} successfully!',
                              ),
                            ),
                          );
                        } else {
                          messenger.showSnackBar(
                            const SnackBar(
                              content: Text('Failed to record deposit.'),
                            ),
                          );
                        }
                      },
                    ).animate().fadeIn(delay: 300.ms),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
