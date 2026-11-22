from celery import Celery

from app.bootstrap.settings import Settings


def create_celery_app(settings: Settings) -> Celery:
    app = Celery("duxue", broker=settings.redis_url, backend=settings.redis_url)
    if settings.redis_key_prefix:
        app.conf.update(
            broker_transport_options={"global_keyprefix": settings.redis_key_prefix},
            result_backend_transport_options={"global_keyprefix": settings.redis_key_prefix},
            result_expires=3600,
        )
    return app
