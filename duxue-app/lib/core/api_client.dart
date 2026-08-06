import 'dart:async';
import 'package:dio/dio.dart';
import 'models.dart';
import 'token_storage.dart';

class ApiClient {
  ApiClient({required String baseUrl, required this.tokens}) {
    dio = Dio(BaseOptions(baseUrl: baseUrl));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await tokens.access;
          if (token != null) options.headers['Authorization'] = 'Bearer $token';
          handler.next(options);
        },
        onError: _handleError,
      ),
    );
  }
  late final Dio dio;
  final TokenStorage tokens;
  Completer<String>? _refreshing;

  Future<void> _handleError(
    DioException error,
    ErrorInterceptorHandler handler,
  ) async {
    if (error.response?.statusCode != 401 ||
        error.requestOptions.path.contains('/auth/refresh') ||
        error.requestOptions.extra['retried'] == true) {
      return handler.next(error);
    }
    try {
      final token = await _refreshOnce();
      final request = error.requestOptions;
      request.headers['Authorization'] = 'Bearer $token';
      request.extra['retried'] = true;
      handler.resolve(await dio.fetch(request));
    } catch (_) {
      await tokens.clear();
      handler.next(error);
    }
  }

  Future<String> _refreshOnce() async {
    if (_refreshing != null) return _refreshing!.future;
    _refreshing = Completer<String>();
    try {
      final refresh = await tokens.refresh;
      if (refresh == null) throw StateError('No refresh token');
      final response = await Dio(
        BaseOptions(baseUrl: dio.options.baseUrl),
      ).post('/auth/refresh', data: {'refresh_token': refresh});
      final access = response.data['access_token'] as String;
      await tokens.save(access, response.data['refresh_token']);
      _refreshing!.complete(access);
      return access;
    } catch (error, stack) {
      _refreshing!.completeError(error, stack);
      rethrow;
    } finally {
      _refreshing = null;
    }
  }

  Future<void> login(String email, String password) async {
    final response = await dio.post(
      '/auth/login',
      data: {'email': email, 'password': password},
    );
    await tokens.save(
      response.data['access_token'],
      response.data['refresh_token'],
    );
  }

  Future<void> register(String name, String email, String password) async {
    final response = await dio.post(
      '/auth/register',
      data: {'name': name, 'email': email, 'password': password},
    );
    await tokens.save(
      response.data['access_token'],
      response.data['refresh_token'],
    );
  }

  Future<List<Ward>> wards() async => ((await dio.get('/wards')).data as List)
      .map((item) => Ward.fromJson(item))
      .toList();
  Future<Ward> createWard(String name) async => Ward.fromJson(
        (await dio.post('/wards', data: {'display_name': name})).data,
      );
  Future<Ward> updateWard(String wardId, {String? analysisProfileId}) async =>
      Ward.fromJson(
        (await dio.patch(
          '/wards/$wardId',
          data: {'analysis_profile_id': analysisProfileId},
        ))
            .data,
      );
  Future<Map<String, dynamic>> invite(String wardId) async =>
      Map<String, dynamic>.from(
        (await dio.post('/wards/$wardId/devices/invite')).data,
      );
  Future<List<Device>> devices(String wardId) async =>
      ((await dio.get('/wards/$wardId/devices')).data as List)
          .map((item) => Device.fromJson(item))
          .toList();
  Future<DailyReport> report(String wardId, DateTime date) async {
    final day = date.toIso8601String().substring(0, 10);
    return DailyReport.fromJson(
      (await dio.get(
        '/reports/daily',
        queryParameters: {'ward_id': wardId, 'date': day},
      ))
          .data,
    );
  }

  Future<WeeklyTrend> weeklyTrend(String wardId, DateTime endDate) async =>
      WeeklyTrend.fromJson(
        (await dio.get(
          '/reports/weekly-trend',
          queryParameters: {'ward_id': wardId, 'end_date': _day(endDate)},
        ))
            .data,
      );
  Future<List<AnalysisProfile>> profiles() async =>
      ((await dio.get('/analysis-profiles')).data as List<dynamic>)
          .map(
            (item) => AnalysisProfile.fromJson(
              Map<String, dynamic>.from(item as Map),
            ),
          )
          .toList();
  Future<AnalysisProfile> profile(String id) async => AnalysisProfile.fromJson(
        Map<String, dynamic>.from(
          (await dio.get('/analysis-profiles/$id')).data as Map,
        ),
      );
  Future<AnalysisProfile> createProfile({
    required String name,
    required String prompt,
  }) async =>
      AnalysisProfile.fromJson(
        Map<String, dynamic>.from(
          (await dio.post(
            '/analysis-profiles',
            data: {'name': name, 'extra_observation_prompt': prompt},
          ))
              .data as Map,
        ),
      );
  Future<AnalysisProfile> updateProfile(
    String id, {
    required String name,
    required String prompt,
  }) async =>
      AnalysisProfile.fromJson(
        Map<String, dynamic>.from(
          (await dio.patch(
            '/analysis-profiles/$id',
            data: {'name': name, 'extra_observation_prompt': prompt},
          ))
              .data as Map,
        ),
      );
  Future<void> deleteProfile(String id) async =>
      dio.delete('/analysis-profiles/$id');
  Future<BehaviorLabel> saveLabel(
    String profileId, {
    String? labelId,
    required String name,
    required Map<String, List<String>> prototypes,
    required int priority,
    required bool isActive,
  }) async {
    final data = {
      'label_name': name,
      'field_prototypes': prototypes,
      'priority': priority,
      'is_active': isActive,
    };
    final response = labelId == null
        ? await dio.post('/analysis-profiles/$profileId/labels', data: data)
        : await dio.patch(
            '/analysis-profiles/$profileId/labels/$labelId',
            data: data,
          );
    return BehaviorLabel.fromJson(
      Map<String, dynamic>.from(response.data as Map),
    );
  }

  Future<void> deleteLabel(String profileId, String labelId) async =>
      dio.delete('/analysis-profiles/$profileId/labels/$labelId');
  String _day(DateTime value) => value.toIso8601String().substring(0, 10);
}
