from unittest.mock import MagicMock, patch

import pytest
from src.config import Config
from src.request_manager import RequestManager


@pytest.fixture
def mock_config():
    """Create a mock config for testing"""
    config = MagicMock(spec=Config)
    config.API_HOST = "https://api.example.com"
    config.CHAT_BOT_API_KEY = "test_api_key"
    config.API_ADMIN_USERNAME = "admin"
    config.API_ADMIN_PASSWORD = "password123"
    return config


@pytest.fixture
def request_manager(mock_config):
    """Create RequestManager instance with mock config"""
    return RequestManager(mock_config)


class TestRequestManagerAuth:
    """Test authentication methods"""

    @patch("src.request_manager.requests.post")
    def test_get_initial_auth_token_success(self, mock_post, request_manager):
        """Test successful initial authentication"""
        # Mock successful auth response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access": "access_token_123",
            "refresh": "refresh_token_456",
        }
        mock_post.return_value = mock_response

        # Test initial auth
        token = request_manager._RequestManager__get_auth_token(initial=True)

        assert token == "access_token_123"
        assert request_manager._RequestManager__refresh_token == "refresh_token_456"

        # Verify API call
        mock_post.assert_called_once_with(
            "https://api.example.com/account/token/",
            json={"tg_id": "admin", "password": "password123"},
            headers={"content-type": "application/json"},
        )

    @patch("src.request_manager.requests.post")
    def test_get_initial_auth_token_failure(self, mock_post, request_manager):
        """Test failed initial authentication"""
        # Mock failed auth response
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        # Test should raise PermissionError
        with pytest.raises(PermissionError) as exc_info:
            request_manager._RequestManager__get_auth_token(initial=True)

        assert "Failed to get initial auth tokens" in str(exc_info.value)
        assert "401" in str(exc_info.value)

    @patch("src.request_manager.requests.post")
    def test_get_refresh_auth_token_success(self, mock_post, request_manager):
        """Test successful token refresh"""
        # Set existing refresh token
        request_manager._RequestManager__refresh_token = "refresh_token_456"

        # Mock successful refresh response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access": "new_access_token_789"}
        mock_post.return_value = mock_response

        # Test refresh
        token = request_manager._RequestManager__get_auth_token(initial=False)

        assert token == "new_access_token_789"

        # Verify API call
        mock_post.assert_called_once_with(
            "https://api.example.com/account/token-refresh/",
            json={"refresh": "refresh_token_456"},
            headers={"content-type": "application/json"},
        )

    @patch("src.request_manager.requests.post")
    def test_get_refresh_auth_token_fallback_to_initial(
        self, mock_post, request_manager
    ):
        """Test refresh failure falls back to initial auth"""
        # Set existing refresh token
        request_manager._RequestManager__refresh_token = "refresh_token_456"

        # Mock refresh failure, then successful initial auth
        mock_post.side_effect = [
            # First call (refresh) fails
            MagicMock(status_code=401),
            # Second call (initial) succeeds
            MagicMock(
                status_code=200,
                json=lambda: {"access": "fallback_token", "refresh": "new_refresh"},
            ),
        ]

        # Test should fallback to initial auth
        token = request_manager._RequestManager__get_auth_token(initial=False)

        assert token == "fallback_token"
        assert mock_post.call_count == 2


class TestRequestManagerHTTPMethods:
    """Test HTTP method wrappers"""

    @patch("src.request_manager.requests.get")
    def test_get_request(self, mock_get, request_manager):
        """Test GET request with proper headers"""
        # Mock auth token generation
        with patch.object(
            request_manager,
            "_RequestManager__get_auth_token",
            return_value="test_token",
        ):
            mock_response = MagicMock()
            mock_get.return_value = mock_response

            result = request_manager.get("/test/endpoint")

            assert result == mock_response
            mock_get.assert_called_once_with(
                "https://api.example.com/test/endpoint",
                headers={
                    "Authorization": "Bearer test_token",
                    "content-type": "application/json",
                },
            )

    @patch("src.request_manager.requests.get")
    def test_get_request_connection_error(self, mock_get, request_manager):
        """Test GET request raises ConnectionError when API is unavailable"""
        with patch.object(
            request_manager,
            "_RequestManager__get_auth_token",
            return_value="test_token",
        ):
            # Simulate upstream API connection failure
            def fake_db_call(*args, **kwargs):
                raise ConnectionError("DB is unavailable")

            mock_get.side_effect = fake_db_call

            with pytest.raises(ConnectionError) as exc_info:
                request_manager.get("/test/endpoint")

            assert "API service is unavailable" in str(exc_info.value)

    @patch("src.request_manager.requests.post")
    def test_post_request_with_body(self, mock_post, request_manager):
        """Test POST request with JSON body"""
        with patch.object(
            request_manager,
            "_RequestManager__get_auth_token",
            return_value="test_token",
        ):
            mock_response = MagicMock()
            mock_post.return_value = mock_response

            test_body = {"key": "value", "number": 123}
            result = request_manager.post("/test/endpoint", test_body)

            assert result == mock_response
            mock_post.assert_called_once_with(
                "https://api.example.com/test/endpoint",
                json=test_body,
                headers={
                    "Authorization": "Bearer test_token",
                    "content-type": "application/json",
                },
            )

    @patch("src.request_manager.requests.patch")
    def test_patch_request(self, mock_patch, request_manager):
        """Test PATCH request"""
        with patch.object(
            request_manager,
            "_RequestManager__get_auth_token",
            return_value="test_token",
        ):
            mock_response = MagicMock()
            mock_patch.return_value = mock_response

            test_body = {"update": "data"}
            result = request_manager.patch("/test/endpoint", test_body)

            assert result == mock_response
            mock_patch.assert_called_once_with(
                "https://api.example.com/test/endpoint",
                json=test_body,
                headers={
                    "Authorization": "Bearer test_token",
                    "content-type": "application/json",
                },
            )

    @patch("src.request_manager.requests.delete")
    def test_delete_request(self, mock_delete, request_manager):
        """Test DELETE request"""
        with patch.object(
            request_manager,
            "_RequestManager__get_auth_token",
            return_value="test_token",
        ):
            mock_response = MagicMock()
            mock_delete.return_value = mock_response

            test_body = {"confirm": True}
            result = request_manager.delete("/test/endpoint", test_body)

            assert result == mock_response
            mock_delete.assert_called_once_with(
                "https://api.example.com/test/endpoint",
                json=test_body,
                headers={
                    "Authorization": "Bearer test_token",
                    "content-type": "application/json",
                },
            )


class TestRequestManagerEndpointFormatting:
    """Test endpoint URL formatting"""

    def test_endpoint_without_leading_slash(self, request_manager):
        """Test that endpoints without leading slash get one added"""
        with patch("src.request_manager.requests.get") as mock_get:
            with patch.object(
                request_manager,
                "_RequestManager__get_auth_token",
                return_value="test_token",
            ):
                request_manager.get("test/endpoint")

                # Should add leading slash
                mock_get.assert_called_once_with(
                    "https://api.example.com/test/endpoint",
                    headers={
                        "Authorization": "Bearer test_token",
                        "content-type": "application/json",
                    },
                )

    def test_endpoint_with_leading_slash(self, request_manager):
        """Test that endpoints with leading slash remain unchanged"""
        with patch("src.request_manager.requests.get") as mock_get:
            with patch.object(
                request_manager,
                "_RequestManager__get_auth_token",
                return_value="test_token",
            ):
                request_manager.get("/test/endpoint")

                # Should keep existing leading slash
                mock_get.assert_called_once_with(
                    "https://api.example.com/test/endpoint",
                    headers={
                        "Authorization": "Bearer test_token",
                        "content-type": "application/json",
                    },
                )


class TestRequestManagerHeaderGeneration:
    """Test header generation and auth token caching"""

    def test_create_default_headers_initial_auth(self, request_manager):
        """Test header creation when no refresh token exists"""
        with patch.object(
            request_manager, "_RequestManager__get_auth_token"
        ) as mock_get_token:
            mock_get_token.return_value = "initial_token"

            headers = request_manager.create_default_headers()

            assert headers == {
                "Authorization": "Bearer initial_token",
                "content-type": "application/json",
            }
            mock_get_token.assert_called_once_with(True)  # initial=True

    def test_create_default_headers_refresh_auth(self, request_manager):
        """Test header creation when refresh token exists"""
        # Set existing refresh token
        request_manager._RequestManager__refresh_token = "existing_refresh"

        with patch.object(
            request_manager, "_RequestManager__get_auth_token"
        ) as mock_get_token:
            mock_get_token.return_value = "refresh_token"

            headers = request_manager.create_default_headers()

            assert headers == {
                "Authorization": "Bearer refresh_token",
                "content-type": "application/json",
            }
            mock_get_token.assert_called_once_with(False)  # initial=False
