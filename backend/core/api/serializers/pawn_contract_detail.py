from rest_framework import serializers


class PawnPaymentItemSerializer(serializers.Serializer):
    paid_at = serializers.DateTimeField()
    amount = serializers.CharField()
    interest_paid = serializers.CharField()
    principal_paid = serializers.CharField()
    note = serializers.CharField()


class PawnRenewalItemSerializer(serializers.Serializer):
    renewed_at = serializers.DateTimeField()
    previous_due_date = serializers.DateField()
    new_due_date = serializers.DateField()
    amount_charged = serializers.CharField()
    interest_charged = serializers.CharField()
    fee_charged = serializers.CharField()
    note = serializers.CharField()