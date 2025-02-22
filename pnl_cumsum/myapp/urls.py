# myapp/urls.py
from django.urls import path
from .views import plot_pnl

urlpatterns = [
    path('chart/', plot_chart, name='plot_chart'),
]