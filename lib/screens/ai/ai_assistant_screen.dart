import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../config/app_colors.dart';
import '../../services/api_service.dart';

class AiAssistantScreen extends StatefulWidget {
  const AiAssistantScreen({super.key});

  @override
  State<AiAssistantScreen> createState() => _AiAssistantScreenState();
}

class _AiAssistantScreenState extends State<AiAssistantScreen> {
  final TextEditingController _controller = TextEditingController();
  final ApiService _api = ApiService();

  final List<_ChatMessage> _messages = [
    _ChatMessage(
      role: 'assistant',
      text:
          'Hi! I can help with budgeting, saving, responsible borrowing, and questions about your Nzeru account. Finance questions share a limited Nzeru account summary with our AI service to prepare an answer. Do not share bank passwords, PINs, or verification codes.',
    ),
  ];

  bool _isSending = false;
  bool _hasAskedQuestion = false;

  final List<String> _quickPrompts = [
    'How am I doing with savings?',
    'Help me make a weekly budget',
    'How much can I safely set aside?',
    'Explain my savings progress',
  ];

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _sendMessage([String? prompt]) async {
    final text = (prompt ?? _controller.text).trim();
    if (text.isEmpty || _isSending) return;

    setState(() {
      _messages.add(_ChatMessage(role: 'user', text: text));
      _isSending = true;
      _hasAskedQuestion = true;
    });

    _controller.clear();
    FocusScope.of(context).unfocus();

    var reply = 'I could not get a response just now. Please try again.';
    try {
      final previousMessages = _messages
          .skip(1)
          .take(_messages.length - 2)
          .toList();
      final history = previousMessages
          .skip(previousMessages.length > 10 ? previousMessages.length - 10 : 0)
          .map(
            (message) => <String, String>{
              'role': message.role,
              'content': message.text,
            },
          )
          .toList();
      final result = await _api.askAssistant(message: text, history: history);
      reply = result['reply']?.toString().trim().isNotEmpty == true
          ? result['reply'].toString().trim()
          : 'I could not get a response just now. Please try again.';
    } on ApiException catch (error) {
      reply = _apiErrorMessage(error);
    } catch (_) {
      reply = 'I could not reach the assistant. Check your connection and try again.';
    }

    if (!mounted) return;
    setState(() {
      _messages.add(_ChatMessage(role: 'assistant', text: reply));
      _isSending = false;
    });
  }

  String _apiErrorMessage(ApiException error) {
    try {
      final body = jsonDecode(error.body);
      if (body is Map && body['detail'] is String) {
        return body['detail'] as String;
      }
    } catch (_) {
      // Fall through to a friendly generic message.
    }
    return error.statusCode == 401
        ? 'Please sign in again to use the assistant.'
        : 'The assistant is temporarily unavailable. Please try again.';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        elevation: 0,
        leading: IconButton(
          onPressed: () => Navigator.pop(context),
          icon: const Icon(Icons.arrow_back, color: AppColors.textPrimary),
        ),
        title: Text(
          'Nzeru Finance Coach',
          style: GoogleFonts.poppins(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: AppColors.textPrimary,
          ),
        ),
      ),
      body: SafeArea(
        child: Column(
          children: [
            Container(
              margin: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                gradient: AppColors.tiffanyGradient,
                borderRadius: BorderRadius.circular(20),
              ),
              child: Row(
                children: [
                  Container(
                    width: 42,
                    height: 42,
                    decoration: const BoxDecoration(
                      color: Colors.white24,
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.auto_awesome, color: Colors.white),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                          'Practical help with saving, budgeting, loans, and your Nzeru account.',
                      style: GoogleFonts.poppins(
                        color: Colors.white,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            AnimatedSize(
              duration: const Duration(milliseconds: 360),
              curve: Curves.easeInOutCubic,
              alignment: Alignment.topCenter,
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 300),
                switchInCurve: Curves.easeOutCubic,
                switchOutCurve: Curves.easeInCubic,
                transitionBuilder: (child, animation) => ClipRect(
                  child: SizeTransition(
                    sizeFactor: animation,
                    axisAlignment: -1,
                    child: FadeTransition(
                      opacity: animation,
                      child: SlideTransition(
                        position: Tween<Offset>(
                          begin: const Offset(0, -0.24),
                          end: Offset.zero,
                        ).animate(animation),
                        child: child,
                      ),
                    ),
                  ),
                ),
                child: _hasAskedQuestion
                    ? const SizedBox.shrink(key: ValueKey('prompts-hidden'))
                    : Padding(
                        key: const ValueKey('prompts-visible'),
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        child: Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: _quickPrompts
                              .map(
                                (prompt) => ActionChip(
                                  label: Text(
                                    prompt,
                                    style: GoogleFonts.poppins(
                                      fontSize: 12,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  backgroundColor: AppColors.primaryTiffanyLight,
                                  onPressed: _isSending
                                      ? null
                                      : () => _sendMessage(prompt),
                                ),
                              )
                              .toList(),
                        ),
                      ),
              ),
            ),
            const SizedBox(height: 12),
            Expanded(
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                itemCount: _messages.length,
                separatorBuilder: (_, __) => const SizedBox(height: 10),
                itemBuilder: (context, index) {
                  final message = _messages[index];
                  final isUser = message.role == 'user';

                  return Align(
                    alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
                    child: Container(
                      constraints: BoxConstraints(
                        maxWidth: MediaQuery.of(context).size.width * 0.78,
                      ),
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                      decoration: BoxDecoration(
                        color: isUser ? AppColors.primaryTiffany : Colors.white,
                        borderRadius: BorderRadius.only(
                          topLeft: const Radius.circular(16),
                          topRight: const Radius.circular(16),
                          bottomLeft: Radius.circular(isUser ? 16 : 4),
                          bottomRight: Radius.circular(isUser ? 4 : 16),
                        ),
                        border: Border.all(
                          color: isUser ? AppColors.primaryTiffany : AppColors.border,
                        ),
                      ),
                      child: Text(
                        message.text,
                        style: GoogleFonts.poppins(
                          color: isUser ? Colors.white : AppColors.textPrimary,
                          fontSize: 13,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
            if (_isSending)
              const LinearProgressIndicator(
                minHeight: 2,
                color: AppColors.primaryTiffany,
                backgroundColor: AppColors.primaryTiffanyLight,
              ),
            Container(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border(
                  top: BorderSide(color: AppColors.border, width: 1),
                ),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      enabled: !_isSending,
                      minLines: 1,
                      maxLines: 3,
                      onSubmitted: (_) => _sendMessage(),
                      decoration: InputDecoration(
                        hintText: 'Ask about your finances...',
                        hintStyle: GoogleFonts.poppins(
                          color: AppColors.textTertiary,
                          fontSize: 13,
                        ),
                        filled: true,
                        fillColor: AppColors.background,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(16),
                          borderSide: BorderSide.none,
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 14,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Container(
                    decoration: BoxDecoration(
                      gradient: AppColors.tiffanyGradient,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: IconButton(
                      onPressed: _isSending ? null : () => _sendMessage(),
                      icon: const Icon(Icons.send_rounded, color: Colors.white),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ChatMessage {
  final String role;
  final String text;

  _ChatMessage({required this.role, required this.text});
}
