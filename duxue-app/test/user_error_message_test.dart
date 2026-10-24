import 'package:dio/dio.dart';
import 'package:duxue_app/core/user_error_message.dart';
import 'package:duxue_app/core/voice_transcription_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  DioException httpError(int status) {
    final request = RequestOptions(path: '/private?token=secret');
    return DioException(
      requestOptions: request,
      response: Response(
        requestOptions: request,
        statusCode: status,
        data: {'detail': 'internal secret'},
      ),
      type: DioExceptionType.badResponse,
    );
  }

  test('HTTP failures show action guidance without response details', () {
    expect(userErrorMessage(httpError(400)), '提交内容不符合要求，请检查后重试');
    expect(userErrorMessage(httpError(401)), '登录已过期，请重新登录');
    expect(userErrorMessage(httpError(403)), '没有权限执行此操作');
    expect(userErrorMessage(httpError(404)), '内容不存在或已被删除');
    expect(userErrorMessage(httpError(409)), '内容已发生变化，请刷新后重试');
    expect(userErrorMessage(httpError(429)), '操作过于频繁，请稍后重试');
    expect(userErrorMessage(httpError(503)), '服务暂时不可用，请稍后重试');
  });

  test('network and unexpected failures do not expose exception text', () {
    final request = RequestOptions(path: '/private?token=secret');
    final network = DioException(
      requestOptions: request,
      type: DioExceptionType.connectionError,
      error: 'secret endpoint is down',
    );
    expect(userErrorMessage(network), '无法连接服务，请检查网络后重试');
    expect(userErrorMessage(StateError('private detail')), '操作未完成，请稍后重试');
  });

  test('voice protocol errors use stable user-facing messages', () {
    expect(voiceProtocolErrorMessage('unauthorized'), '登录已过期，请重新登录');
    expect(voiceProtocolErrorMessage('configuration'), '语音识别暂不可用，请稍后重试');
    expect(voiceProtocolErrorMessage(null), '语音识别暂不可用，请稍后重试');
  });
}
