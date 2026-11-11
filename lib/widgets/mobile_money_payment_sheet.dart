import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

enum MalawiMobileMoneyProvider { airtelMoney, tnmMpamba }

class MobileMoneyPaymentChoice {
  final String gateway;
  final MalawiMobileMoneyProvider provider;

  const MobileMoneyPaymentChoice({
    this.gateway = 'PayChangu',
    required this.provider,
  });

  String get providerName => switch (provider) {
    MalawiMobileMoneyProvider.airtelMoney => 'Airtel Money',
    MalawiMobileMoneyProvider.tnmMpamba => 'TNM Mpamba',
  };
}

Future<MobileMoneyPaymentChoice?> showMobileMoneyPaymentSheet(
  BuildContext context, {
  required String action,
  required double amount,
}) {
  return showModalBottomSheet<MobileMoneyPaymentChoice>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (context) => _MobileMoneyPaymentSheet(
      action: action,
      amount: amount,
    ),
  );
}

class _MobileMoneyPaymentSheet extends StatelessWidget {
  final String action;
  final double amount;

  const _MobileMoneyPaymentSheet({required this.action, required this.amount});

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Container(
        padding: EdgeInsets.fromLTRB(
          22,
          12,
          22,
          22 + MediaQuery.viewInsetsOf(context).bottom,
        ),
        decoration: const BoxDecoration(
          color: Color(0xFFF8FAFC),
          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 42,
                height: 4,
                decoration: BoxDecoration(
                  color: const Color(0xFFCBD5E1),
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            ),
            const SizedBox(height: 20),
            Text(
              action == 'Deposit' ? 'Choose how to add funds' : 'Choose where to receive funds',
              style: GoogleFonts.poppins(fontSize: 19, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 5),
            Text(
              'MK ${amount.toStringAsFixed(2)}  ·  PayChangu',
              style: GoogleFonts.poppins(color: const Color(0xFF64748B), fontSize: 13),
            ),
            const SizedBox(height: 18),
            _ProviderTile(
              name: 'Airtel Money',
              subtitle: 'Mobile money',
              mark: 'A',
              color: const Color(0xFFE31E2F),
              onTap: () => Navigator.pop(
                context,
                const MobileMoneyPaymentChoice(provider: MalawiMobileMoneyProvider.airtelMoney),
              ),
            ),
            const SizedBox(height: 10),
            _ProviderTile(
              name: 'TNM Mpamba',
              subtitle: 'Mobile money',
              mark: 'TNM',
              color: const Color(0xFF009B4D),
              onTap: () => Navigator.pop(
                context,
                const MobileMoneyPaymentChoice(provider: MalawiMobileMoneyProvider.tnmMpamba),
              ),
            ),
            const SizedBox(height: 14),
            Center(
              child: Text(
                'Demo payment flow',
                style: GoogleFonts.poppins(fontSize: 11, color: const Color(0xFF94A3B8)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProviderTile extends StatelessWidget {
  final String name;
  final String subtitle;
  final String mark;
  final Color color;
  final VoidCallback onTap;

  const _ProviderTile({
    required this.name,
    required this.subtitle,
    required this.mark,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Container(
          padding: const EdgeInsets.all(15),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: const Color(0xFFE2E8F0)),
          ),
          child: Row(
            children: [
              Container(
                width: 48,
                height: 48,
                alignment: Alignment.center,
                decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(14)),
                child: Text(mark, style: GoogleFonts.poppins(color: Colors.white, fontWeight: FontWeight.w800, fontSize: mark.length > 1 ? 13 : 24)),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name, style: GoogleFonts.poppins(fontWeight: FontWeight.w700, fontSize: 15)),
                    Text(subtitle, style: GoogleFonts.poppins(color: const Color(0xFF64748B), fontSize: 12)),
                  ],
                ),
              ),
              const Icon(Icons.arrow_forward_ios_rounded, size: 16, color: Color(0xFF94A3B8)),
            ],
          ),
        ),
      ),
    );
  }
}
