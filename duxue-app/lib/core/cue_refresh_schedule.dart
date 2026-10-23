/// Time until the next wall-clock minute divisible by five.
Duration nextCueRefreshDelay(DateTime now) {
  final next = DateTime(
    now.year,
    now.month,
    now.day,
    now.hour,
    (now.minute ~/ 5 + 1) * 5,
  );
  return next.difference(now);
}
