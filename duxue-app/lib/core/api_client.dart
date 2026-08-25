import 'dart:async';
import 'dart:typed_data';
import 'package:dio/dio.dart';
import 'models.dart';
import 'token_storage.dart';

class ApiClient {
  ApiClient({required String baseUrl, required this.tokens}) {
    dio = Dio(_options(baseUrl));
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

  static BaseOptions _options(String baseUrl) => BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: const Duration(seconds: 10),
        sendTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 20),
      );

  Future<void> _handleError(
    DioException error,
    ErrorInterceptorHandler handler,
  ) async {
    if (error.response?.statusCode != 401 ||
        error.requestOptions.path.contains('/auth/refresh') ||
        error.requestOptions.extra['retried'] == true ||
        await tokens.wardId != null) {
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
      final response = await Dio(_options(dio.options.baseUrl)).post(
        '/auth/refresh',
        data: {'refresh_token': refresh},
      );
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
  Future<Ward> createWard(String name, String gradeStage) async =>
      Ward.fromJson(
        (await dio.post('/wards',
                data: {'display_name': name, 'grade_stage': gradeStage}))
            .data,
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
  Future<Map<String, dynamic>> createAssignment(
          String wardId, String title) async =>
      Map<String, dynamic>.from(
          (await dio.post('/wards/$wardId/assignments', data: {'title': title}))
              .data);
  Future<Map<String, dynamic>> respondToTaskIntake({
    required String content,
    required List<Map<String, dynamic>> history,
    required List<Map<String, dynamic>> tasks,
    required List<String> attachmentKeys,
  }) async =>
      Map<String, dynamic>.from((await dio.post('/task-intake/respond', data: {
        'content': content,
        'history': history,
        'tasks': tasks,
        'attachment_keys': attachmentKeys,
      }))
          .data);

  Future<String> uploadTaskIntakeImage(
      Uint8List bytes, String extension) async {
    final contentType =
        extension.toLowerCase() == 'png' ? 'image/png' : 'image/jpeg';
    final signed = Map<String, dynamic>.from((await dio.post(
      '/task-intake/upload-url',
      data: {'extension': extension, 'content_type': contentType},
    ))
        .data);
    await Dio().put(
      signed['upload_url'] as String,
      data: bytes,
      options:
          Options(headers: Map<String, dynamic>.from(signed['headers'] as Map)),
    );
    return signed['oss_key'] as String;
  }

  Future<void> confirmTaskIntake(
          List<Map<String, dynamic>> tasks, List<String> attachmentKeys) =>
      dio.post('/task-intake/confirm',
          data: {'tasks': tasks, 'attachment_keys': attachmentKeys});

  Future<void> cleanupTaskIntake(List<String> attachmentKeys) => dio
      .post('/task-intake/cleanup', data: {'attachment_keys': attachmentKeys});
  Future<Map<String, dynamic>> wardInvite(String wardId) async =>
      Map<String, dynamic>.from(
          (await dio.post('/wards/$wardId/login-invite')).data);
  Future<String> bindWard(String code) async {
    final data = Map<String, dynamic>.from(
        (await dio.post('/ward-auth/bind', data: {'invite_code': code})).data);
    await tokens.saveWard(
        data['access_token'] as String, data['ward_id'] as String);
    return data['ward_id'] as String;
  }

  Future<Map<String, dynamic>> wardProfile() async =>
      Map<String, dynamic>.from((await dio.get('/ward/profile')).data as Map);

  Future<List<dynamic>> assignments(String wardId) async =>
      (await dio.get('/wards/$wardId/assignments')).data as List<dynamic>;
  Future<Map<String, dynamic>> savePlan(String wardId, DateTime day,
          List<Map<String, dynamic>> items) async =>
      Map<String, dynamic>.from((await dio.put(
              '/wards/$wardId/plans/${_day(day)}',
              data: {'plan_date': _day(day), 'items': items}))
          .data);
  Future<void> confirmPlan(String wardId, DateTime day) =>
      dio.post('/wards/$wardId/plans/${_day(day)}/confirm');
  Future<Map<String, dynamic>> plan(String wardId, DateTime day) async =>
      Map<String, dynamic>.from(
          (await dio.get('/wards/$wardId/plans/${_day(day)}')).data);
  Future<Map<String, dynamic>> startSession(String itemId) async =>
      Map<String, dynamic>.from(
          (await dio.post('/plan-items/$itemId/sessions')).data);
  Future<Map<String, dynamic>> startAssignmentSession(
          String assignmentId) async =>
      Map<String, dynamic>.from(
          (await dio.post('/assignments/$assignmentId/sessions')).data);
  Future<Map<String, dynamic>> resumeSession(String sessionId) async =>
      Map<String, dynamic>.from(
          (await dio.post('/sessions/$sessionId/resume')).data);
  Future<Map<String, dynamic>> pauseSession(
          String sessionId, int seconds) async =>
      Map<String, dynamic>.from((await dio.post('/sessions/$sessionId/pause',
              data: {'active_seconds': seconds}))
          .data);
  Future<String> ask(String sessionId, String content) async => (await dio
          .post('/sessions/$sessionId/messages', data: {'content': content}))
      .data['content'] as String;
  Future<void> finishSession(String sessionId, int seconds) => dio
      .post('/sessions/$sessionId/finish', data: {'active_seconds': seconds});
  Future<void> review(String wardId, DateTime day, String feeling) =>
      dio.post('/wards/$wardId/reviews/${_day(day)}',
          data: {'feeling': feeling, 'timeline_json': []});
  Future<Map<String, dynamic>> insight(String wardId, DateTime day) async =>
      Map<String, dynamic>.from(
          (await dio.get('/wards/$wardId/reviews/${_day(day)}/insight')).data);
  Future<Map<String, dynamic>> guardianStory(
          String wardId, DateTime day) async =>
      Map<String, dynamic>.from(
          (await dio.get('/wards/$wardId/guardian-story/${_day(day)}')).data);
  String _day(DateTime value) => value.toIso8601String().substring(0, 10);
}
