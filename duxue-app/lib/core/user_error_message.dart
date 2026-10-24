import 'package:dio/dio.dart';

/// Safe, actionable text for failures shown outside a domain-specific flow.
/// Never expose Dio's request URL, response body, or exception string to users.
String userErrorMessage(Object error) {
  if (error is! DioException) return '操作未完成，请稍后重试';

  switch (error.type) {
    case DioExceptionType.connectionTimeout:
    case DioExceptionType.sendTimeout:
    case DioExceptionType.receiveTimeout:
    case DioExceptionType.transformTimeout:
      return '连接超时，请检查网络后重试';
    case DioExceptionType.connectionError:
      return '无法连接服务，请检查网络后重试';
    case DioExceptionType.badCertificate:
      return '安全连接失败，请稍后重试';
    case DioExceptionType.cancel:
      return '请求已取消，请重试';
    case DioExceptionType.unknown:
      return '网络请求失败，请检查网络后重试';
    case DioExceptionType.badResponse:
      final status = error.response?.statusCode;
      if (status == 400 || status == 422) {
        return '提交内容不符合要求，请检查后重试';
      }
      if (status == 401) return '登录已过期，请重新登录';
      if (status == 403) return '没有权限执行此操作';
      if (status == 404) return '内容不存在或已被删除';
      if (status == 409) return '内容已发生变化，请刷新后重试';
      if (status == 429) return '操作过于频繁，请稍后重试';
      if (status != null && status >= 500) {
        return '服务暂时不可用，请稍后重试';
      }
      return '请求未完成，请稍后重试';
  }
}
