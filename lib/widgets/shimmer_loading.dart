import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

import '../config/app_colors.dart';

class ShimmerBlock extends StatelessWidget {
  final double? width;
  final double height;
  final double radius;

  const ShimmerBlock({
    super.key,
    this.width,
    required this.height,
    this.radius = 12,
  });

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: AppColors.brandBlueLight.withValues(alpha: 0.72),
      highlightColor: Colors.white,
      period: const Duration(milliseconds: 1350),
      child: Container(
        width: width,
        height: height,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(radius),
        ),
      ),
    );
  }
}

class ShimmerLoadingList extends StatelessWidget {
  final int cardCount;

  const ShimmerLoadingList({super.key, this.cardCount = 3});

  @override
  Widget build(BuildContext context) {
    return ListView.separated(
      padding: const EdgeInsets.all(16),
      itemCount: cardCount,
      separatorBuilder: (_, __) => const SizedBox(height: 14),
      itemBuilder: (context, index) => Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: AppColors.cardSurface,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppColors.brandBlue.withAlpha(18)),
          boxShadow: [
            BoxShadow(
              color: AppColors.brandBlueDark.withAlpha(14),
              blurRadius: 18,
              offset: const Offset(0, 7),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: const [
                ShimmerBlock(width: 46, height: 46, radius: 14),
                SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ShimmerBlock(width: 150, height: 14),
                      SizedBox(height: 8),
                      ShimmerBlock(width: 95, height: 10),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            const ShimmerBlock(height: 10),
            const SizedBox(height: 8),
            const ShimmerBlock(width: 190, height: 10),
          ],
        ),
      ),
    );
  }
}
