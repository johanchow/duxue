import 'dart:typed_data';

import 'package:flutter/material.dart';

class ChatImageViewer extends StatefulWidget {
  const ChatImageViewer({
    super.key,
    required this.imageCount,
    required this.initialIndex,
    required this.loadImage,
  });

  final int imageCount;
  final int initialIndex;
  final Future<Uint8List> Function(int index) loadImage;

  @override
  State<ChatImageViewer> createState() => _ChatImageViewerState();
}

class _ChatImageViewerState extends State<ChatImageViewer> {
  late final PageController _pages =
      PageController(initialPage: widget.initialIndex);
  late int _index = widget.initialIndex;
  final _loads = <int, Future<Uint8List>>{};

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        key: const Key('chat-image-viewer'),
        backgroundColor: Colors.black,
        body: SafeArea(
          child: Stack(children: [
            PageView.builder(
              controller: _pages,
              itemCount: widget.imageCount,
              onPageChanged: (index) => setState(() => _index = index),
              itemBuilder: (context, index) => FutureBuilder<Uint8List>(
                future:
                    _loads.putIfAbsent(index, () => widget.loadImage(index)),
                builder: (context, snapshot) {
                  if (snapshot.hasError) {
                    return const Center(
                        child: Text('图片加载失败',
                            style: TextStyle(color: Colors.white)));
                  }
                  if (!snapshot.hasData) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  return InteractiveViewer(
                    minScale: 1,
                    maxScale: 4,
                    child: Center(
                        child: Image.memory(snapshot.data!,
                            fit: BoxFit.contain, gaplessPlayback: true)),
                  );
                },
              ),
            ),
            Positioned(
              top: 0,
              left: 0,
              child: IconButton(
                tooltip: '关闭图片',
                icon: const Icon(Icons.close, color: Colors.white),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ),
            if (widget.imageCount > 1)
              Positioned(
                bottom: 16,
                left: 0,
                right: 0,
                child: Text('${_index + 1}/${widget.imageCount}',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Colors.white)),
              ),
          ]),
        ),
      );
}
