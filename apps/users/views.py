from django.contrib.auth import authenticate
from django_ratelimit.core import is_ratelimited
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import RegisterSerializer, UserDetailSerializer


def _check_ip_rate_limit(request: Request, group: str, rate: str) -> bool:
    return is_ratelimited(request, group=group, key="ip", rate=rate, method="POST", increment=True)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        if _check_ip_rate_limit(request, group="auth-register", rate="5/m"):
            return Response(
                {"status": "error", "data": {}, "message": "Too many registration attempts. Try again in a minute."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"status": "error", "data": serializer.errors, "message": "Registration failed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "status": "success",
                "data": {
                    "user": UserDetailSerializer(user).data,
                    "tokens": {"access": str(refresh.access_token), "refresh": str(refresh)},
                },
                "message": "User registered successfully.",
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        if _check_ip_rate_limit(request, group="auth-login", rate="10/m"):
            return Response(
                {"status": "error", "data": {}, "message": "Too many login attempts. Try again in a minute."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        email = request.data.get("email", "")
        password = request.data.get("password", "")
        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response(
                {"status": "error", "data": {}, "message": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "status": "success",
                "data": {
                    "user": UserDetailSerializer(user).data,
                    "tokens": {"access": str(refresh.access_token), "refresh": str(refresh)},
                },
                "message": "Login successful.",
            }
        )


class TokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = TokenRefreshSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"status": "error", "data": serializer.errors, "message": "Token refresh failed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "status": "success",
                "data": {"access": str(serializer.validated_data["access"])},
                "message": "Token refreshed successfully.",
            }
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(
            {
                "status": "success",
                "data": UserDetailSerializer(request.user).data,
                "message": "",
            }
        )
