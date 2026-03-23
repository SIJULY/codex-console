"""
自定义域名邮箱服务实现
基于 REST API 接口 (已融合私人 API 智能分流)
"""

import re
import time
import json
import random
import string
import logging
import requests
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

from .base import BaseEmailService, EmailServiceError, EmailServiceType
from ..core.http_client import HTTPClient, RequestConfig
from ..config.constants import OTP_CODE_PATTERN

logger = logging.getLogger(__name__)


class MeoMailEmailService(BaseEmailService):
    """
    自定义域名邮箱服务
    支持标准 REST API 接口与私人定制 API 智能分流
    """

    def __init__(self, config: Dict[str, Any] = None, name: str = None):
        super().__init__(EmailServiceType.MOE_MAIL, name)

        required_keys = ["base_url", "api_key"]
        missing_keys = [key for key in required_keys if key not in (config or {})]

        if missing_keys:
            raise ValueError(f"缺少必需配置: {missing_keys}")

        default_config = {
            "base_url": "",
            "api_key": "",
            "api_key_header": "X-API-Key",
            "timeout": 30,
            "max_retries": 3,
            "proxy_url": None,
            "default_domain": None,
            "default_expiry": 3600000,
            # 新增：是否强制启用私人定制 API 模式
            # True: 强制私人模式
            # False: 强制标准模式
            # None: 自动判断
            "custom_private_api": None,
        }

        self.config = {**default_config, **(config or {})}

        self.http_client = HTTPClient(
            proxy_url=self.config.get("proxy_url"),
            config=RequestConfig(
                timeout=self.config["timeout"],
                max_retries=self.config["max_retries"],
            )
        )

        self._emails_cache: Dict[str, Dict[str, Any]] = {}
        self._last_config_check: float = 0
        self._cached_config: Optional[Dict[str, Any]] = None

        # 双模式识别逻辑：
        # 1. 如果配置里明确给了 custom_private_api=True/False，则按配置走
        # 2. 如果没配置，则根据 base_url 自动识别
        self.is_custom_private_api = self._detect_private_api_mode()

        logger.info(
            f"邮箱服务模式: {'私人定制 API 模式' if self.is_custom_private_api else '标准 REST API 模式'} "
            f"(base_url={self.config.get('base_url')})"
        )

    def _detect_private_api_mode(self) -> bool:
        cfg_value = self.config.get("custom_private_api", None)
        if cfg_value is not None:
            if isinstance(cfg_value, str):
                return cfg_value.strip().lower() in ("1", "true", "yes", "on")
            return bool(cfg_value)

        base_url = str(self.config.get("base_url", "")).strip().rstrip("/").lower()

        # 自动识别逻辑：
        # 如果 base_url 明显就是你这种 Flask 私人邮局接口地址，则走私人模式
        # 例如：
        # http://x.x.x.x:2099
        # http://domain.com
        # http://domain.com/MailCode
        # http://domain.com/Mail
        #
        # 标准 REST API 一般会提供 /api/config /api/emails/generate 等接口
        # 你的私人邮局提供 /MailCode /Mail
        #
        # 这里不再绑定固定 IP。
        if base_url.endswith("/mailcode") or base_url.endswith("/mail"):
            return True

        return False

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        api_key_header = self.config.get("api_key_header", "X-API-Key")
        headers[api_key_header] = self.config["api_key"]
        return headers

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        url = urljoin(self.config["base_url"], endpoint)
        kwargs.setdefault("headers", {})
        kwargs["headers"].update(self._get_headers())

        try:
            if method.upper() == "POST":
                kwargs["allow_redirects"] = False
                response = self.http_client.request(method, url, **kwargs)
                max_redirects = 5
                redirect_count = 0
                while response.status_code in (301, 302, 303, 307, 308) and redirect_count < max_redirects:
                    location = response.headers.get("Location", "")
                    if not location:
                        break
                    import urllib.parse as _urlparse
                    redirect_url = _urlparse.urljoin(url, location)
                    if response.status_code in (307, 308):
                        redirect_method = method
                        redirect_kwargs = kwargs
                    else:
                        redirect_method = "GET"
                        redirect_kwargs = {k: v for k, v in kwargs.items() if k not in ("json", "data")}
                    response = self.http_client.request(redirect_method, redirect_url, **redirect_kwargs)
                    url = redirect_url
                    redirect_count += 1
            else:
                response = self.http_client.request(method, url, **kwargs)

            if response.status_code >= 400:
                error_msg = f"API 请求失败: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = f"{error_msg} - {error_data}"
                except Exception:
                    error_msg = f"{error_msg} - {response.text[:200]}"
                self.update_status(False, EmailServiceError(error_msg))
                raise EmailServiceError(error_msg)

            try:
                return response.json()
            except json.JSONDecodeError:
                return {"raw_response": response.text}

        except Exception as e:
            self.update_status(False, e)
            if isinstance(e, EmailServiceError):
                raise
            raise EmailServiceError(f"API 请求失败: {method} {endpoint} - {e}")

    def get_config(self, force_refresh: bool = False) -> Dict[str, Any]:
        # 私人 API：跳过标准 /api/config 健康检查
        if self.is_custom_private_api:
            self.update_status(True)
            return {
                "status": "ok",
                "emailDomains": self.config.get("default_domain", "")
            }

        if not force_refresh and self._cached_config and time.time() - self._last_config_check < 300:
            return self._cached_config

        try:
            response = self._make_request("GET", "/api/config")
            self._cached_config = response
            self._last_config_check = time.time()
            self.update_status(True)
            return response
        except Exception as e:
            logger.warning(f"获取配置失败: {e}")
            return {}

    def create_email(self, config: Dict[str, Any] = None) -> Dict[str, Any]:
        # 私人 API：本地直接生成随机前缀邮箱
        if self.is_custom_private_api:
            request_config = config or {}
            domain = request_config.get("domain") or self.config.get("default_domain")
            if not domain:
                raise EmailServiceError("私人定制 API 模式下缺少 default_domain 或 domain 配置")

            prefix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=14))
            email_address = f"{prefix}@{domain}"
            email_info = {
                "email": email_address,
                "service_id": email_address,
                "id": email_address,
                "created_at": time.time(),
                "expiry": self.config.get("default_expiry", 3600000),
                "domain": domain,
                "raw_response": {"status": "local_generated"},
            }
            self._emails_cache[email_address] = email_info
            logger.info(f"✅ 成功生成私人专属前缀邮箱: {email_address}")
            self.update_status(True)
            return email_info

        # 标准开源版逻辑
        sys_config = self.get_config()
        default_domain = self.config.get("default_domain")
        if not default_domain and sys_config.get("emailDomains"):
            domains = sys_config["emailDomains"].split(",")
            default_domain = domains[0].strip() if domains else None

        request_config = config or {}
        create_data = {
            "name": request_config.get("name", ""),
            "expiryTime": request_config.get("expiryTime", self.config.get("default_expiry", 3600000)),
            "domain": request_config.get("domain", default_domain),
        }

        create_data = {k: v for k, v in create_data.items() if v is not None and v != ""}

        try:
            response = self._make_request("POST", "/api/emails/generate", json=create_data)
            email = response.get("email", "").strip()
            email_id = response.get("id", "").strip()

            if not email or not email_id:
                raise EmailServiceError("API 返回数据不完整")

            email_info = {
                "email": email,
                "service_id": email_id,
                "id": email_id,
                "created_at": time.time(),
                "expiry": create_data.get("expiryTime"),
                "domain": create_data.get("domain"),
                "raw_response": response,
            }

            self._emails_cache[email_id] = email_info
            logger.info(f"成功创建自定义域名邮箱: {email} (ID: {email_id})")
            self.update_status(True)
            return email_info
        except Exception as e:
            self.update_status(False, e)
            if isinstance(e, EmailServiceError):
                raise
            raise EmailServiceError(f"创建邮箱失败: {e}")

    def _strip_html(self, text: str) -> str:
        if not text:
            return ""
        try:
            text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
            text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
            text = re.sub(r"(?is)<[^>]+>", " ", text)
            text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
            text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception:
            return text or ""

    def _extract_code_from_text(self, text: str) -> Optional[str]:
        if not text:
            return None

        normalized = self._strip_html(str(text))

        semantic_patterns = [
            r"(?:your\s+chatgpt\s+code\s+is|your\s+code\s+is|verification\s+code|temporary\s+verification\s+code|authentication\s+code|验证码|驗證碼|検証コード|log-?in\s+code|login\s+code|otp)[^\d]{0,30}(\d{6})",
            r"\bcode\b[^\d]{0,20}(\d{6})",
            r"\botp\b[^\d]{0,20}(\d{6})",
        ]
        for pat in semantic_patterns:
            match = re.search(pat, normalized, re.IGNORECASE)
            if match:
                return match.group(1)

        match = re.search(r"(?<!\d)(\d{6})(?!\d)", normalized)
        if match:
            return match.group(1)

        return None

    def _extract_code_from_payload(self, payload: Any) -> Optional[str]:
        if payload is None:
            return None

        if isinstance(payload, str):
            return self._extract_code_from_text(payload)

        if isinstance(payload, list):
            for item in payload:
                code = self._extract_code_from_payload(item)
                if code:
                    return code
            return None

        if isinstance(payload, dict):
            for key in ("code", "otp", "verification_code", "verificationCode"):
                value = payload.get(key)
                if value is not None:
                    code = self._extract_code_from_text(str(value))
                    if code:
                        return code

            for key in ("subject", "body", "content", "html", "message", "text", "raw_response", "data", "result"):
                value = payload.get(key)
                if value is not None:
                    code = self._extract_code_from_payload(value)
                    if code:
                        return code

            for _, value in payload.items():
                code = self._extract_code_from_payload(value)
                if code:
                    return code

        return None

    def _build_private_api_urls(self) -> Dict[str, str]:
        base_url = self.config.get("base_url", "").strip().rstrip("/")
        if not base_url:
            raise EmailServiceError("base_url 未配置")

        if base_url.lower().endswith("/mailcode"):
            root = base_url[:-9].rstrip("/")
            code_api_url = base_url
            legacy_api_url = f"{root}/Mail"
        elif base_url.lower().endswith("/mail"):
            root = base_url[:-5].rstrip("/")
            legacy_api_url = base_url
            code_api_url = f"{root}/MailCode"
        else:
            code_api_url = f"{base_url}/MailCode"
            legacy_api_url = f"{base_url}/Mail"

        return {
            "code_api_url": code_api_url,
            "legacy_api_url": legacy_api_url,
        }

    def get_verification_code(
        self,
        email: str,
        email_id: str = None,
        timeout: int = 120,
        pattern: str = OTP_CODE_PATTERN,
        otp_sent_at: Optional[float] = None,
    ) -> Optional[str]:
        # 私人 API 分支
        if self.is_custom_private_api:
            logger.info(f"正在向专属私人服务器请求验证码: {email}...")
            start_time = time.time()
            token = str(self.config.get("api_key") or "2088").strip()

            urls = self._build_private_api_urls()
            code_api_url = urls["code_api_url"]
            legacy_api_url = urls["legacy_api_url"]

            session = requests.Session()
            session.headers.update({
                "Accept": "application/json, text/html, text/plain;q=0.9, */*;q=0.8",
                "User-Agent": "Mozilla/5.0 CodexConsole/1.0",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            })

            poll_interval = 3

            while time.time() - start_time < timeout:
                # 1) 优先走新 JSON 接口
                try:
                    params = {
                        "token": token,
                        "mail": email,
                    }
                    if otp_sent_at:
                        params["after"] = str(otp_sent_at)

                    resp = session.get(
                        code_api_url,
                        params=params,
                        timeout=(10, 15),
                        allow_redirects=True,
                    )

                    if resp.status_code == 200:
                        try:
                            payload = resp.json()
                        except Exception:
                            payload = {"raw_response": resp.text}

                        code = self._extract_code_from_payload(payload)
                        if code:
                            logger.info(f"🎉 专属 API 捕获验证码: {code}")
                            self.update_status(True)
                            return code

                    elif resp.status_code not in (404,):
                        logger.debug(f"专属 MailCode 返回状态码异常: {resp.status_code}, email={email}")

                except Exception as e:
                    logger.debug(f"专属 MailCode 请求轮询中... ({e})")

                # 2) 只有在没有 otp_sent_at 时才回退旧接口
                if not otp_sent_at:
                    try:
                        resp = session.get(
                            legacy_api_url,
                            params={
                                "token": token,
                                "mail": email,
                            },
                            timeout=(10, 15),
                            allow_redirects=True,
                        )

                        if resp.status_code == 200:
                            code = self._extract_code_from_text(resp.text)
                            if code:
                                logger.info(f"🎉 专属 API 捕获验证码(旧接口): {code}")
                                self.update_status(True)
                                return code

                    except Exception as e:
                        logger.debug(f"专属 Mail 旧接口请求轮询中... ({e})")

                time.sleep(poll_interval)

            logger.warning(f"❌ 等待专属服务器验证码超时: {email}")
            return None

        # ------------------- 标准开源版逻辑 -------------------
        target_email_id = email_id
        if not target_email_id:
            for eid, info in self._emails_cache.items():
                if info.get("email") == email:
                    target_email_id = eid
                    break

        if not target_email_id:
            logger.warning(f"未找到邮箱 {email} 的 ID，无法获取验证码")
            return None

        logger.info(f"正在从自定义域名邮箱 {email} 获取验证码...")
        start_time = time.time()
        seen_message_ids = set()

        while time.time() - start_time < timeout:
            try:
                response = self._make_request("GET", f"/api/emails/{target_email_id}")
                messages = response.get("messages", [])
                if not isinstance(messages, list):
                    time.sleep(3)
                    continue

                for message in messages:
                    message_id = message.get("id")
                    if not message_id or message_id in seen_message_ids:
                        continue

                    seen_message_ids.add(message_id)
                    sender = str(message.get("from_address", "")).lower()
                    subject = str(message.get("subject", ""))

                    message_content = self._get_message_content(target_email_id, message_id)
                    if not message_content:
                        continue

                    content = f"{sender} {subject} {message_content}"
                    if "openai" not in sender and "openai" not in content.lower():
                        continue

                    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
                    match = re.search(pattern, re.sub(email_pattern, "", content))
                    if match:
                        code = match.group(1)
                        logger.info(f"从自定义域名邮箱 {email} 找到验证码: {code}")
                        self.update_status(True)
                        return code

            except Exception as e:
                logger.debug(f"检查邮件时出错: {e}")

            time.sleep(3)

        logger.warning(f"等待验证码超时: {email}")
        return None

    def _get_message_content(self, email_id: str, message_id: str) -> Optional[str]:
        try:
            response = self._make_request("GET", f"/api/emails/{email_id}/{message_id}")
            message = response.get("message", {})
            content = message.get("content", "")
            if not content:
                html = message.get("html", "")
                if html:
                    content = re.sub(r"<[^>]+>", " ", html)
            return content
        except Exception as e:
            logger.debug(f"获取邮件内容失败: {e}")
            return None

    def list_emails(self, cursor: str = None, **kwargs) -> List[Dict[str, Any]]:
        if self.is_custom_private_api:
            return list(self._emails_cache.values())

        params = {}
        if cursor:
            params["cursor"] = cursor
        try:
            response = self._make_request("GET", "/api/emails", params=params)
            emails = response.get("emails", [])
            for email_info in emails:
                email_id = email_info.get("id")
                if email_id:
                    self._emails_cache[email_id] = email_info
            self.update_status(True)
            return emails
        except Exception as e:
            logger.warning(f"列出邮箱失败: {e}")
            self.update_status(False, e)
            return []

    def delete_email(self, email_id: str) -> bool:
        if self.is_custom_private_api:
            self._emails_cache.pop(email_id, None)
            return True

        try:
            response = self._make_request("DELETE", f"/api/emails/{email_id}")
            success = response.get("success", False)
            if success:
                self._emails_cache.pop(email_id, None)
                logger.info(f"成功删除邮箱: {email_id}")
            else:
                logger.warning(f"删除邮箱失败: {email_id}")
            self.update_status(success)
            return success
        except Exception as e:
            logger.error(f"删除邮箱失败: {email_id} - {e}")
            self.update_status(False, e)
            return False

    def check_health(self) -> bool:
        try:
            config = self.get_config(force_refresh=True)
            if config:
                logger.debug("自定义域名邮箱服务健康检查通过")
                self.update_status(True)
                return True
            else:
                logger.warning("自定义域名邮箱服务健康检查失败：获取配置为空")
                self.update_status(False, EmailServiceError("获取配置为空"))
                return False
        except Exception as e:
            logger.warning(f"自定义域名邮箱服务健康检查失败: {e}")
            self.update_status(False, e)
            return False

    def get_email_messages(self, email_id: str, cursor: str = None) -> List[Dict[str, Any]]:
        if self.is_custom_private_api:
            return []
        params = {}
        if cursor:
            params["cursor"] = cursor
        try:
            response = self._make_request("GET", f"/api/emails/{email_id}", params=params)
            messages = response.get("messages", [])
            self.update_status(True)
            return messages
        except Exception as e:
            logger.error(f"获取邮件列表失败: {email_id} - {e}")
            self.update_status(False, e)
            return []

    def get_message_detail(self, email_id: str, message_id: str) -> Optional[Dict[str, Any]]:
        if self.is_custom_private_api:
            return None
        try:
            response = self._make_request("GET", f"/api/emails/{email_id}/{message_id}")
            message = response.get("message")
            self.update_status(True)
            return message
        except Exception as e:
            logger.error(f"获取邮件详情失败: {email_id}/{message_id} - {e}")
            self.update_status(False, e)
            return None

    def create_email_share(self, email_id: str, expires_in: int = 86400000) -> Optional[Dict[str, Any]]:
        if self.is_custom_private_api:
            return None
        try:
            response = self._make_request("POST", f"/api/emails/{email_id}/share", json={"expiresIn": expires_in})
            self.update_status(True)
            return response
        except Exception as e:
            logger.error(f"创建邮箱分享链接失败: {email_id} - {e}")
            self.update_status(False, e)
            return None

    def create_message_share(self, email_id: str, message_id: str, expires_in: int = 86400000) -> Optional[Dict[str, Any]]:
        if self.is_custom_private_api:
            return None
        try:
            response = self._make_request(
                "POST",
                f"/api/emails/{email_id}/messages/{message_id}/share",
                json={"expiresIn": expires_in}
            )
            self.update_status(True)
            return response
        except Exception as e:
            logger.error(f"创建邮件分享链接失败: {email_id}/{message_id} - {e}")
            self.update_status(False, e)
            return None

    def get_service_info(self) -> Dict[str, Any]:
        config = self.get_config()
        return {
            "service_type": self.service_type.value,
            "name": self.name,
            "base_url": self.config["base_url"],
            "default_domain": self.config.get("default_domain"),
            "custom_private_api": self.is_custom_private_api,
            "system_config": config,
            "cached_emails_count": len(self._emails_cache),
            "status": self.status.value,
        }
