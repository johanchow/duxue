import 'dart:async';
import 'package:dio/dio.dart';
import 'models.dart';
import 'token_storage.dart';

class ApiClient {
  ApiClient({required String baseUrl, required this.tokens}) {
    dio = Dio(BaseOptions(baseUrl: baseUrl));
    dio.interceptors.add(InterceptorsWrapper(onRequest: (options, handler) async {
      final token = await tokens.access;
      if (token != null) options.headers['Authorization'] = 'Bearer $token';
      handler.next(options);
    }, onError: _handleError));
  }
  late final Dio dio;
  final TokenStorage tokens;
  Completer<String>? _refreshing;

  Future<void> _handleError(DioException error, ErrorInterceptorHandler handler) async {
    if (error.response?.statusCode != 401 || error.requestOptions.path.contains('/auth/refresh') || error.requestOptions.extra['retried'] == true) return handler.next(error);
    try {
      final token = await _refreshOnce();
      final request = error.requestOptions;
      request.headers['Authorization'] = 'Bearer $token';
      request.extra['retried'] = true;
      handler.resolve(await dio.fetch(request));
    } catch (_) { await tokens.clear(); handler.next(error); }
  }

  Future<String> _refreshOnce() async {
    if (_refreshing != null) return _refreshing!.future;
    _refreshing = Completer<String>();
    try {
      final refresh = await tokens.refresh;
      if (refresh == null) throw StateError('No refresh token');
      final response = await Dio(BaseOptions(baseUrl: dio.options.baseUrl)).post('/auth/refresh', data: {'refresh_token': refresh});
      final access = response.data['access_token'] as String;
      await tokens.save(access, response.data['refresh_token']);
      _refreshing!.complete(access); return access;
    } catch (error, stack) { _refreshing!.completeError(error, stack); rethrow; }
    finally { _refreshing = null; }
  }

  Future<void> login(String email, String password) async {
    final response = await dio.post('/auth/login', data: {'email': email, 'password': password});
    await tokens.save(response.data['access_token'], response.data['refresh_token']);
  }
  Future<void> register(String name, String email, String password) async {
    final response = await dio.post('/auth/register', data: {'name': name, 'email': email, 'password': password});
    await tokens.save(response.data['access_token'], response.data['refresh_token']);
  }
  Future<List<Ward>> wards() async => ((await dio.get('/wards')).data as List).map((item) => Ward.fromJson(item)).toList();
  Future<Ward> createWard(String name) async => Ward.fromJson((await dio.post('/wards', data: {'display_name': name})).data);
  Future<Map<String, dynamic>> invite(String wardId) async => Map<String, dynamic>.from((await dio.post('/wards/$wardId/devices/invite')).data);
  Future<List<Device>> devices(String wardId) async => ((await dio.get('/wards/$wardId/devices')).data as List).map((item) => Device.fromJson(item)).toList();
  Future<DailyReport> report(String wardId, DateTime date) async {
    final day = date.toIso8601String().substring(0, 10);
    return DailyReport.fromJson((await dio.get('/reports/daily', queryParameters: {'ward_id': wardId, 'date': day})).data);
  }
}
