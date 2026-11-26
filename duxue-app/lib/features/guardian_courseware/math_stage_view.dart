import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// P0-1 Interactive MathStage host widget for MentorCourseware.
///
/// Renders the 3 preset `component_scene` types (`coord_plane_2d`,
/// `geometry_2d`, `solid_geometry_3d`) at 60fps with drag/unfold gestures and
/// automatically degrades a single step to verified static SVG/text on error.
class MathStageView extends StatefulWidget {
  const MathStageView({
    required this.visualSpec,
    this.simulateError = false,
    super.key,
  });

  final Map<String, dynamic> visualSpec;
  final bool simulateError;

  @override
  State<MathStageView> createState() => _MathStageViewState();
}

class _MathStageViewState extends State<MathStageView> {
  double _rotX = 0.45;
  double _rotY = -0.65;
  double _unfold = 0.0;
  double _movableX = 2.33;
  String? _stageError;

  static const _supported = {
    'coord_plane_2d',
    'geometry_2d',
    'solid_geometry_3d',
  };

  @override
  void initState() {
    super.initState();
    _checkSpec();
  }

  @override
  void didUpdateWidget(covariant MathStageView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.visualSpec != widget.visualSpec ||
        oldWidget.simulateError != widget.simulateError) {
      _stageError = null;
      _checkSpec();
    }
  }

  void _checkSpec() {
    if (widget.simulateError) {
      _stageError = 'stage_runtime_error';
      return;
    }
    final kind = widget.visualSpec['kind'] as String?;
    if (kind == 'component_scene') {
      final payload = widget.visualSpec['payload'];
      final comp = payload is Map ? payload['component'] as String? : null;
      if (comp == null || !_supported.contains(comp)) {
        _stageError = 'unsupported_component';
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final kind = widget.visualSpec['kind'] as String? ?? 'layered_svg';
    final title = widget.visualSpec['title'] as String? ?? '';
    final payload = widget.visualSpec['payload'] is Map
        ? Map<String, dynamic>.from(widget.visualSpec['payload'] as Map)
        : const <String, dynamic>{};

    if (_stageError != null ||
        kind != 'component_scene' ||
        payload['degraded'] == true) {
      return _buildStaticFallback(context, title, payload);
    }

    final component = payload['component'] as String;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = isDark ? const Color(0xff0c1222) : const Color(0xfff8fafc);
    final border =
        isDark ? const Color(0xff1e293b) : const Color(0xffe2e8f0);

    return Container(
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (title.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
              child: Text(
                title,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: isDark ? Colors.white70 : const Color(0xff334155),
                ),
              ),
            ),
          SizedBox(
            height: 230,
            child: GestureDetector(
              onPanUpdate: (d) {
                setState(() {
                  if (component == 'solid_geometry_3d') {
                    _rotY += d.delta.dx * 0.012;
                    _rotX = (_rotX + d.delta.dy * 0.012).clamp(-1.2, 1.2);
                  } else if (component == 'coord_plane_2d' &&
                      payload['movable_x'] == true) {
                    _movableX = (_movableX + d.delta.dx * 0.02).clamp(0.2, 5.8);
                  }
                });
              },
              child: CustomPaint(
                painter: _MathStagePainter(
                  component: component,
                  payload: payload,
                  isDark: isDark,
                  rotX: _rotX,
                  rotY: _rotY,
                  unfold: _unfold,
                  movableX: _movableX,
                ),
                size: Size.infinite,
              ),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              border: Border(top: BorderSide(color: border)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    component == 'solid_geometry_3d'
                        ? '单指拖转 3D 立体模型'
                        : (payload['movable_x'] == true
                            ? '左右拖动 P 点观察最值变化'
                            : '交互数理图示'),
                    style: TextStyle(
                      fontSize: 11,
                      color: isDark ? Colors.white60 : const Color(0xff64748b),
                    ),
                  ),
                ),
                if (component == 'solid_geometry_3d' &&
                    (payload['shape'] ?? 'cube') == 'cube') ...[
                  const Text('展开', style: TextStyle(fontSize: 11)),
                  SizedBox(
                    width: 100,
                    child: Slider(
                      value: _unfold,
                      onChanged: (v) => setState(() => _unfold = v),
                    ),
                  ),
                ],
                TextButton(
                  onPressed: () => setState(() {
                    _rotX = 0.45;
                    _rotY = -0.65;
                    _unfold = 0.0;
                    _movableX = 2.33;
                  }),
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    minimumSize: const Size(0, 28),
                  ),
                  child: const Text('重置', style: TextStyle(fontSize: 11)),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStaticFallback(
    BuildContext context,
    String title,
    Map<String, dynamic> payload,
  ) {
    final svg = (widget.visualSpec['static_fallback_svg'] as String?) ??
        (payload['svg'] as String?);
    final text = (widget.visualSpec['static_fallback_text'] as String?) ??
        (payload['fallback_text'] as String?) ??
        (widget.visualSpec['alt'] as String?) ??
        '已切换为静态图文展示';
    return Container(
      key: const ValueKey('math-stage-static-fallback'),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xfff1f5f9),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xffcbd5e1)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (title.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(title,
                  style: const TextStyle(
                      fontSize: 12, fontWeight: FontWeight.w600)),
            ),
          if (svg != null && svg.trim().startsWith('<svg'))
            SizedBox(height: 160, child: SvgPicture.string(svg))
          else
            Row(
              children: [
                const Icon(Icons.image_outlined,
                    size: 16, color: Color(0xff475569)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(text,
                      style: const TextStyle(
                          fontSize: 13, color: Color(0xff334155))),
                ),
              ],
            ),
        ],
      ),
    );
  }
}

class _MathStagePainter extends CustomPainter {
  _MathStagePainter({
    required this.component,
    required this.payload,
    required this.isDark,
    required this.rotX,
    required this.rotY,
    required this.unfold,
    required this.movableX,
  });

  final String component;
  final Map<String, dynamic> payload;
  final bool isDark;
  final double rotX;
  final double rotY;
  final double unfold;
  final double movableX;

  Color get _base => isDark ? const Color(0xff38bdf8) : const Color(0xff0284c7);
  Color get _aux => isDark ? const Color(0xff34d399) : const Color(0xff059669);
  Color get _focus => isDark ? const Color(0xfffbbf24) : const Color(0xffd97706);
  Color get _result =>
      isDark ? const Color(0xfffb7185) : const Color(0xffe11d48);
  Color get _muted => isDark ? Colors.white38 : const Color(0xff94a3b8);

  @override
  void paint(Canvas canvas, Size size) {
    if (component == 'solid_geometry_3d') {
      _paintSolid3D(canvas, size);
    } else if (component == 'geometry_2d') {
      _paintGeometry2D(canvas, size);
    } else {
      _paintCoordPlane2D(canvas, size);
    }
  }

  void _paintCoordPlane2D(Canvas canvas, Size size) {
    final ox = size.width * 0.16;
    final oy = size.height * 0.68;
    final s = math.min(size.width, size.height) / 8.0;
    Offset pt(double x, double y) => Offset(ox + x * s, oy - y * s);

    final axis = Paint()
      ..color = _base
      ..strokeWidth = 2;
    canvas.drawLine(Offset(12, oy), Offset(size.width - 12, oy), axis);
    canvas.drawLine(Offset(ox, size.height - 12), Offset(ox, 12),
        Paint()..color = _muted..strokeWidth = 1.4);

    final rawPts = (payload['points'] as List?) ??
        const [
          {'id': 'A', 'x': 1, 'y': 2},
          {'id': 'B', 'x': 5, 'y': 4},
        ];
    final points = <Offset>[];
    for (final item in rawPts) {
      if (item is! Map) continue;
      final x = (item['x'] as num?)?.toDouble() ?? 0;
      final y = (item['y'] as num?)?.toDouble() ?? 0;
      final o = pt(x, y);
      points.add(o);
      canvas.drawCircle(o, 5, Paint()..color = _base);
    }
    if (payload['movable_x'] == true && points.length >= 2) {
      final p = pt(movableX, 0);
      final line = Paint()
        ..color = _focus
        ..strokeWidth = 2.4;
      canvas.drawLine(points[0], p, line);
      canvas.drawLine(p, points[1], line);
      canvas.drawCircle(p, 6, Paint()..color = _result);
    } else if (points.length >= 2) {
      canvas.drawLine(points[0], points[1],
          Paint()..color = _aux..strokeWidth = 2.2);
    }
  }

  void _paintGeometry2D(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final s = math.min(size.width, size.height) * 0.34;
    final a = Offset(cx - 0.8 * s, cy + 0.5 * s);
    final b = Offset(cx + 0.9 * s, cy + 0.5 * s);
    final c = Offset(cx + 0.1 * s, cy - 0.8 * s);
    final line = Paint()
      ..color = _base
      ..strokeWidth = 2.2;
    canvas.drawLine(a, b, line);
    canvas.drawLine(b, c, line);
    canvas.drawLine(c, a, line);
    final mid = Offset((a.dx + b.dx) / 2, (a.dy + b.dy) / 2);
    canvas.drawLine(c, mid, Paint()..color = _aux..strokeWidth = 2);
    for (final o in [a, b, c, mid]) {
      canvas.drawCircle(o, 4.5, Paint()..color = _result);
    }
  }

  void _paintSolid3D(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final s = math.min(size.width, size.height) * 0.28;
    final cosY = math.cos(rotY), sinY = math.sin(rotY);
    final cosX = math.cos(rotX), sinX = math.sin(rotX);

    (Offset, double) proj(List<double> v) {
      final x1 = v[0] * cosY - v[2] * sinY;
      final z1 = v[0] * sinY + v[2] * cosY;
      final y2 = v[1] * cosX - z1 * sinX;
      final z2 = v[1] * sinX + z1 * cosX;
      final d = 4.2 / (4.2 - z2);
      return (Offset(cx + x1 * s * d, cy - y2 * s * d), z2);
    }

    final shape = (payload['shape'] as String?) ?? 'cube';
    late final List<List<double>> verts;
    late final List<List<int>> edges;
    if (shape == 'pyramid') {
      verts = [
        [-1, -0.7, -1],
        [1, -0.7, -1],
        [1, -0.7, 1],
        [-1, -0.7, 1],
        [0, 1.1, 0],
      ];
      edges = [
        [0, 1], [1, 2], [2, 3], [3, 0],
        [0, 4], [1, 4], [2, 4], [3, 4],
      ];
    } else {
      final ang = unfold * (math.pi / 2);
      List<double> rotFront(List<double> p) {
        final dx = p[0] - 1, dz = p[2] - 1;
        return [
          1 + dx * math.cos(ang) - dz * math.sin(ang),
          p[1],
          1 + dx * math.sin(ang) + dz * math.cos(ang),
        ];
      }

      verts = [
        [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
        rotFront([-1, -1, 1]), [1, -1, 1], [1, 1, 1], rotFront([-1, 1, 1]),
      ];
      edges = [
        [0, 1], [1, 2], [2, 3], [3, 0],
        [4, 5], [5, 6], [6, 7], [7, 4],
        [0, 4], [1, 5], [2, 6], [3, 7],
      ];
    }

    final projected = verts.map(proj).toList();
    // Highlight translucent cross-section
    final sectionPath = Path();
    final secIdx = shape == 'pyramid' ? [0, 2, 4] : [0, 1, 6, 7];
    for (var i = 0; i < secIdx.length; i++) {
      final p = projected[secIdx[i]].$1;
      if (i == 0) {
        sectionPath.moveTo(p.dx, p.dy);
      } else {
        sectionPath.lineTo(p.dx, p.dy);
      }
    }
    sectionPath.close();
    canvas.drawPath(
      sectionPath,
      Paint()..color = _aux.withValues(alpha: 0.18),
    );

    for (final e in edges) {
      final a = projected[e[0]];
      final b = projected[e[1]];
      final avgZ = (a.$2 + b.$2) / 2;
      canvas.drawLine(
        a.$1,
        b.$1,
        Paint()
          ..color = avgZ < -0.35 ? _muted : _base
          ..strokeWidth = avgZ < -0.35 ? 1.4 : 2.2,
      );
    }
    final dEnd = shape == 'pyramid' ? 4 : 6;
    canvas.drawLine(
      projected[0].$1,
      projected[dEnd].$1,
      Paint()
        ..color = _result
        ..strokeWidth = 2.8,
    );
  }

  @override
  bool shouldRepaint(covariant _MathStagePainter old) =>
      old.rotX != rotX ||
      old.rotY != rotY ||
      old.unfold != unfold ||
      old.movableX != movableX ||
      old.component != component ||
      old.isDark != isDark;
}
