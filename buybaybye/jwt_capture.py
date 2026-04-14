from __future__ import annotations

import asyncio


def handle_response(response, *, handle_response_async_func) -> None:
    """Запустить асинхронный поиск JWT токена в ответе."""
    asyncio.create_task(handle_response_async_func(response))


async def handle_response_async(response, *, set_jwt_token_func, color_cyan: str, color_reset: str) -> None:
    """Асинхронная обработка ответа для поиска JWT токена."""
    try:
        auth_header = response.headers.get("authorization", "")
        if "eyJ" in auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if "." in token:
                set_jwt_token_func(token)
                print(f"{color_cyan}🔥 JWT НАЙДЕН в заголовке Authorization: {token[:50]}...{color_reset}", flush=True)
                return

        text = await response.text()
        if "eyJ" in text:
            start_idx = text.find("eyJ")
            if start_idx != -1:
                end_idx = start_idx
                while end_idx < len(text) and (text[end_idx].isalnum() or text[end_idx] in "_-"):
                    end_idx += 1

                potential_token = text[start_idx:end_idx]
                if potential_token.count(".") >= 1:
                    set_jwt_token_func(potential_token)
                    print(f"{color_cyan}🔥 JWT НАЙДЕН в теле ответа: {potential_token[:50]}...{color_reset}", flush=True)
    except Exception:
        pass


def handle_request(request, *, set_jwt_token_func, color_cyan: str, color_reset: str) -> None:
    """Перехватить запрос и поискать JWT токен в URL, заголовках и теле запроса."""
    try:
        url = request.url
        if "token=" in url:
            start_idx = url.find("token=") + 6
            end_idx = url.find("&", start_idx)
            if end_idx == -1:
                end_idx = len(url)

            potential_token = url[start_idx:end_idx]
            if "eyJ" in potential_token and potential_token.count(".") >= 1:
                set_jwt_token_func(potential_token)
                print(f"{color_cyan}🔥 JWT НАЙДЕН в URL параметре: {potential_token[:50]}...{color_reset}", flush=True)
                return

        auth_header = request.headers.get("Authorization", "")
        if "Bearer eyJ" in auth_header:
            token = auth_header.replace("Bearer ", "").strip()
            if "." in token:
                set_jwt_token_func(token)
                print(f"{color_cyan}🔥 JWT НАЙДЕН в заголовке Authorization запроса: {token[:50]}...{color_reset}", flush=True)
                return

        referer = request.headers.get("Referer", "")
        if "token=" in referer:
            start_idx = referer.find("token=") + 6
            end_idx = referer.find("&", start_idx)
            if end_idx == -1:
                end_idx = len(referer)

            potential_token = referer[start_idx:end_idx]
            if "eyJ" in potential_token and potential_token.count(".") >= 1:
                set_jwt_token_func(potential_token)
                print(f"{color_cyan}🔥 JWT НАЙДЕН в Referer заголовке: {potential_token[:50]}...{color_reset}", flush=True)
                return

        try:
            post_data = request.post_data
            if post_data and "eyJ" in post_data:
                start_idx = post_data.find("eyJ")
                if start_idx != -1:
                    end_idx = start_idx
                    while end_idx < len(post_data) and (post_data[end_idx].isalnum() or post_data[end_idx] in "_-"):
                        end_idx += 1

                    potential_token = post_data[start_idx:end_idx]
                    if potential_token.count(".") >= 1:
                        set_jwt_token_func(potential_token)
                        print(f"{color_cyan}🔥 JWT НАЙДЕН в теле запроса: {potential_token[:50]}...{color_reset}", flush=True)
        except Exception:
            pass
    except Exception:
        pass


def subscribe_jwt_search_to_page(page, *, response_handler, request_handler) -> None:
    """Подписать поиск JWT токена на события ответов и запросов страницы."""
    page.on("response", response_handler)
    page.on("request", request_handler)