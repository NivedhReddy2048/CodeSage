from django.urls import path

from apps.reviews.consumers import ReviewProgressConsumer

websocket_urlpatterns = [
    path("ws/reviews/<int:review_id>/", ReviewProgressConsumer.as_asgi()),
]
