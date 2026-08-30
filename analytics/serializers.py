from rest_framework import serializers

from analytics.models import DailyLoad, WeeklySummary


class DailyLoadSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyLoad
        fields = "__all__"


class WeeklySummarySerializer(serializers.ModelSerializer):
    risk_flag_display = serializers.CharField(source="get_risk_flag_display", read_only=True)

    class Meta:
        model = WeeklySummary
        fields = "__all__"
