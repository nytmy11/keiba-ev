from django.urls import path

from . import views

urlpatterns = [
    path("dates/", views.DatesView.as_view()),
    path("day/<str:date>/", views.DayView.as_view()),
    path("push/<str:date>/", views.PushView.as_view()),  # 公開版のみ（合言葉が無ければ 403）
]
