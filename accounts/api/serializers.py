from django.db import transaction
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from profiles.api.serializers import WorkerProfileSerializer
from profiles.models import CustomerProfile, WorkerProfile

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    username = serializers.RegexField(regex=r'^[A-Za-z0-9._-]{3,30}$', max_length=30)
    is_admin = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'phone', 'full_name', 'profile_picture',
            'is_customer', 'is_worker', 'is_admin',
            'is_email_verified', 'is_phone_verified', 'date_joined'
        )
        read_only_fields = (
            'id', 'is_customer', 'is_worker', 'is_admin',
            'is_email_verified', 'is_phone_verified', 'date_joined',
        )

    def validate_email(self, value):
        users = User.objects.filter(email__iexact=value)
        if self.instance:
            users = users.exclude(pk=self.instance.pk)
        if users.exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_username(self, value):
        users = User.objects.filter(username__iexact=value)
        if self.instance:
            users = users.exclude(pk=self.instance.pk)
        if users.exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)
    username = serializers.RegexField(regex=r'^[A-Za-z0-9._-]{3,30}$', required=False, max_length=30)
    account_type = serializers.ChoiceField(
        choices=('customer', 'worker', 'both'),
        required=False,
    )
    is_worker = serializers.BooleanField(required=False, write_only=True)

    class Meta:
        model = User
        fields = ('email', 'username', 'phone', 'full_name', 'password', 'password2', 'account_type', 'is_worker')

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({'password': "Password fields didn't match."})
        account_type = attrs.pop('account_type', None)
        legacy_is_worker = attrs.pop('is_worker', False)
        if account_type:
            attrs['is_customer'] = account_type in ('customer', 'both')
            attrs['is_worker'] = account_type in ('worker', 'both')
        else:
            attrs['is_customer'] = True
            attrs['is_worker'] = legacy_is_worker
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop('password2')
        password = validated_data.pop('password')
        is_customer = validated_data.pop('is_customer')
        is_worker = validated_data.pop('is_worker')
        user = User.objects.create_user(password=password, **validated_data,
                                        is_customer=is_customer, is_worker=is_worker)

        if is_customer:
            CustomerProfile.objects.get_or_create(user=user)
        if is_worker:
            WorkerProfile.objects.get_or_create(user=user)

        return user

    def to_representation(self, instance):
        return UserSerializer(instance, context=self.context).data


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['full_name'] = user.full_name
        token['is_customer'] = user.is_customer
        token['is_worker'] = user.is_worker
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user).data
        return data


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])
    new_password2 = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({'new_password': "Password fields didn't match."})
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class WorkerActivationResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    user = UserSerializer()
    worker_profile = WorkerProfileSerializer()
