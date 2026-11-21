import 'dart:math' as math;
import 'dart:ui';

import 'package:path_parsing/path_parsing.dart';
import 'package:xml/xml.dart';

/// flutter_svg ignores marker definitions. Expand endpoint markers into ordinary
/// SVG groups so the arrow follows the tangent even on an elliptical orbit.
String expandSvgMarkers(String svg) {
  if (!svg.contains('<marker')) return svg;
  final XmlDocument document;
  try {
    document = XmlDocument.parse(svg);
  } on XmlException {
    return svg;
  }
  final markers = {
    for (final marker in document.findAllElements('marker'))
      if (marker.getAttribute('id') != null) marker.getAttribute('id')!: marker,
  };
  for (final element in document.descendants.whereType<XmlElement>().toList()) {
    if (element.ancestors
        .whereType<XmlElement>()
        .any((e) => e.name.local == 'defs' || e.name.local == 'marker')) {
      continue;
    }
    for (final endpoint in ['start', 'end']) {
      final ref = element.getAttribute('marker-$endpoint');
      if (ref == null) continue;
      final id = RegExp(r'^url\(#([\w.-]+)\)$').firstMatch(ref)?.group(1);
      final marker = markers[id];
      if (marker == null) continue;
      final tangent = _endpoint(element, endpoint == 'start');
      if (tangent == null) continue;
      final transform = _markerTransform(marker, element, tangent, endpoint);
      final group = XmlElement(
          XmlName('g'),
          [
            XmlAttribute(XmlName('transform'), transform),
          ],
          marker.childElements.map((child) => child.copy()));
      final parent = element.parentElement!;
      parent.children.insert(parent.children.indexOf(element) + 1, group);
      element.removeAttribute('marker-$endpoint');
    }
  }
  for (final marker in markers.values) {
    marker.parentElement?.children.remove(marker);
  }
  return document.toXmlString();
}

String _markerTransform(
    XmlElement marker, XmlElement element, Tangent t, String endpoint) {
  double number(XmlElement el, String key, double fallback) =>
      double.tryParse(el.getAttribute(key) ?? '') ?? fallback;
  final box = (marker.getAttribute('viewBox') ?? '')
      .trim()
      .split(RegExp(r'[\s,]+'))
      .map(double.tryParse)
      .toList();
  final scale = box.length == 4 && (box[2] ?? 0) > 0 && (box[3] ?? 0) > 0
      ? math.min(number(marker, 'markerWidth', 3) / box[2]!,
          number(marker, 'markerHeight', 3) / box[3]!)
      : 1.0;
  final unit = marker.getAttribute('markerUnits') == 'userSpaceOnUse'
      ? 1.0
      : number(element, 'stroke-width', 1);
  final orient = marker.getAttribute('orient');
  final degrees = orient == 'auto' || orient == 'auto-start-reverse'
      ? t.vector.direction * 180 / math.pi +
          (orient == 'auto-start-reverse' && endpoint == 'start' ? 180 : 0)
      : double.tryParse(orient ?? '') ?? 0;
  return "${element.getAttribute('transform') ?? ''} translate(${t.position.dx} ${t.position.dy}) "
      "rotate($degrees) scale(${scale * unit}) translate(${-number(marker, 'refX', 0)} ${-number(marker, 'refY', 0)})";
}

Tangent? _endpoint(XmlElement element, bool start) {
  final d = switch (element.name.local) {
    'line' =>
      "M${element.getAttribute('x1') ?? 0} ${element.getAttribute('y1') ?? 0} L${element.getAttribute('x2') ?? 0} ${element.getAttribute('y2') ?? 0}",
    'polyline' => "M${element.getAttribute('points') ?? ''}",
    'path' => element.getAttribute('d'),
    _ => null,
  };
  if (d == null) return null;
  final path = _MarkerPath();
  try {
    writeSvgPathDataToPath(d, path);
  } on FormatException {
    return null;
  } on StateError {
    return null;
  }
  final metrics = path.path.computeMetrics().toList();
  if (metrics.isEmpty) return null;
  final segment = start ? metrics.first : metrics.last;
  return segment.getTangentForOffset(start ? 0 : segment.length);
}

class _MarkerPath implements PathProxy {
  final path = Path();
  @override
  void moveTo(double x, double y) => path.moveTo(x, y);
  @override
  void lineTo(double x, double y) => path.lineTo(x, y);
  @override
  void cubicTo(
          double x1, double y1, double x2, double y2, double x3, double y3) =>
      path.cubicTo(x1, y1, x2, y2, x3, y3);
  @override
  void close() => path.close();
}
