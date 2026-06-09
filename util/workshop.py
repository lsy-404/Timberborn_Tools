"""
version: 1.1.0
author: Wuyilingwei
Get the latest mods from the Steam Workshop
"""
import logging
import requests
from bs4 import BeautifulSoup


def get_published_file_details(mod_ids: list, batch_size: int = 100) -> dict:
    """
    Batch query ISteamRemoteStorage/GetPublishedFileDetails/v1/ (no API key needed).
    Returns {mod_id: time_updated} for all mods that responded successfully.
    """
    logger = logging.getLogger("get_published_file_details")
    result = {}
    total = len(mod_ids)

    for i in range(0, total, batch_size):
        batch = mod_ids[i:i + batch_size]
        data = {"itemcount": len(batch)}
        for j, mod_id in enumerate(batch):
            data[f"publishedfileids[{j}]"] = mod_id
        try:
            resp = requests.post(
                "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                data=data,
                timeout=30,
            )
            if resp.status_code == 200:
                details = resp.json().get("response", {}).get("publishedfiledetails", [])
                for item in details:
                    if item.get("result", 0) != 1:
                        continue
                    pid = str(item.get("publishedfileid", ""))
                    t_updated = item.get("time_updated", 0)
                    if pid and t_updated:
                        result[pid] = t_updated
            else:
                logger.warning(f"GetPublishedFileDetails HTTP {resp.status_code} on batch {i // batch_size + 1}")
        except Exception as e:
            logger.error(f"GetPublishedFileDetails failed on batch {i // batch_size + 1}: {e}")

    logger.info(f"Got update times for {len(result)}/{total} mods")
    return result


class WorkshopNewMods:
    """
    Class to get the latest mods from the Steam Workshop
    """
    game_id: int
    text: str
    headers: dict
    ids: list[int]
    logger: logging.Logger

    def __init__(self, game_id: int, text: str = "Mod",
                 headers: dict = None) -> None:
        self.ids = []
        self.game_id = game_id
        self.text = text
        if headers is None:
            self.headers = {'User-Agent': 'Mozilla/5.0 '
                            '(Windows NT 10.0; Win64; x64) '
                            'AppleWebKit/537.36 (KHTML, like Gecko) '
                            'Chrome/121.0.0.0 Safari/537.36',
                            'Accept-Language': 'en-US,en;q=0.9'}
        else:
            self.headers = headers
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_mods(self, depth: int = 1, days: int = -1) -> list[int]:
        """
        Returns a list of the latest mods from the Steam Workshop
        depth: the number of pages to search for mods
        days: only include mods updated within the last N days (-1 = no limit)
        """
        def response_to_ids(response: requests.Response) -> None:
            soup = BeautifulSoup(response.content, 'html.parser')
            mod_elements = soup.find_all('a', {'class': 'ugc'})
            for mod in mod_elements:
                mod_url = mod.get('href')
                if mod_url and 'id=' in mod_url:
                    mod_text = mod_url.split('id=')[-1]
                    mod_id = mod_text.split('&')[0]
                    if mod_id not in self.ids:
                        self.ids.append(mod_id)
            self.ids.sort()
        for i in range(1, depth + 1):
            url = (f'https://steamcommunity.com/workshop/browse/'
                   f'?appid={self.game_id}&browsesort=mostrecent'
                   f'&requiredtags%5B%5D={self.text}&p={i}')
            if days > 0:
                url += f'&days={days}'
            self.logger.info(f'Getting mods from page {i}')
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                response_to_ids(response)
            else:
                self.logger.warning(f'Failed to get mods from page {i}')
        self.logger.info(f'Got {len(self.ids)} mod IDs from {depth} pages')
        return self.ids


if __name__ == '__main__':
    fetcher = WorkshopNewMods(1062090)
    fetcher.get_mods(3)


class SteamAPIWorkshop:
    """
    Class to query the Steam Workshop via the official Steam Web API
    (IPublishedFileService/QueryFiles), with support for
    RankedByLastUpdatedDate sorting and incremental updates.
    """
    base_url: str
    api_key: str
    game_id: int
    text: str
    logger: logging.Logger

    def __init__(self, api_key: str, game_id: int, text: str = "Mod") -> None:
        self.api_key = api_key
        self.game_id = game_id
        self.text = text
        self.base_url = (
            "https://api.steampowered.com/"
            "IPublishedFileService/QueryFiles/v1/"
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    def query_files(self, page: int = 1, numperpage: int = 100,
                    query_type: int = 21) -> dict | None:
        """
        Call QueryFiles API with RankedByLastUpdatedDate (21) by default.

        Returns the JSON response as a dict, or None on failure.
        """
        params = {
            "key": self.api_key,
            "query_type": query_type,
            "page": page,
            "numperpage": numperpage,
            "appid": self.game_id,
            "requiredtags": self.text,
            "match_all_tags": True,
            "return_tags": True,
            "return_short_description": False,
        }
        try:
            resp = requests.get(self.base_url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("response", {})
            else:
                self.logger.warning(
                    f"Steam API returned HTTP {resp.status_code} "
                    f"on page {page}: {resp.text[:200]}"
                )
                return None
        except requests.RequestException as e:
            self.logger.error(f"Steam API request failed on page {page}: {e}")
            return None

    def _filter_by_days(self, publishedfiles: list[dict],
                        days: int) -> list[dict]:
        """
        Filter published files to only those updated within the last N days.
        Uses the 'time_updated' Unix timestamp from the API response.
        """
        if days <= 0:
            return publishedfiles
        import time
        cutoff = int(time.time()) - days * 86400
        filtered = [
            f for f in publishedfiles
            if f.get("time_updated", 0) >= cutoff
        ]
        self.logger.debug(
            f"days={days} filter: {len(filtered)}/{len(publishedfiles)} "
            f"items within {days} days"
        )
        return filtered

    def _extract_ids(self, publishedfiles: list[dict],
                     seen: set | None = None) -> list[str]:
        """Extract publishedfileid strings from API result items."""
        ids: list[str] = []
        seen = seen or set()
        for item in publishedfiles:
            pid = str(item.get("publishedfileid", ""))
            if pid and pid not in seen:
                ids.append(pid)
                seen.add(pid)
        return ids

    def get_all_mod_ids(self, max_pages: int = 10,
                        numperpage: int = 100,
                        days: int = -1) -> list[str]:
        """
        Fetch all mod IDs across multiple pages, sorted by last update (newest first).

        max_pages: safety cap to avoid infinite loops (max 1000 per Steam docs).
        numperpage: results per page.
        days: only include mods updated within the last N days (-1 = no limit).
              Stops pagination early when results fall outside the time window.
        Returns a deduplicated, order-preserving list of mod ID strings.
        """
        ids: list[str] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            self.logger.info(
                f"Fetching page {page}/{max_pages} "
                f"(numperpage={numperpage}, days={days})"
            )
            data = self.query_files(page=page, numperpage=numperpage)
            if data is None:
                self.logger.warning(f"Stopping early at page {page}")
                break

            publishedfiles = data.get("publishedfiledetails", [])
            if not publishedfiles:
                self.logger.info(f"No more results after page {page - 1}")
                break

            # Apply days filter
            if days > 0:
                publishedfiles = self._filter_by_days(publishedfiles, days)

            page_ids = self._extract_ids(publishedfiles, seen)
            ids.extend(page_ids)

            if days > 0 and not page_ids:
                self.logger.info(
                    f"No items within {days} days on page {page} — stopping"
                )
                break

            total = data.get("total", 0)
            if total and page * numperpage >= total:
                self.logger.info(
                    f"Reached end of results (total={total}, fetched {len(ids)})"
                )
                break

        self.logger.info(f"Got {len(ids)} unique mod IDs from API")
        return ids

    def get_incremental_mods(self, existing_ids: list[str],
                             max_pages: int = 3,
                             numperpage: int = 100,
                             days: int = -1) -> list[str]:
        """
        Incremental mode: fetch mods from the API and return only those
        NOT already in existing_ids. Stops early once an entire page of
        results is already known (i.e. we've reached previously-indexed mods).

        days: only consider mods updated within the last N days (-1 = no limit).
        This efficiently catches up on newly updated/published mods.
        """
        new_ids: list[str] = []
        existing_set = set(existing_ids)

        for page in range(1, max_pages + 1):
            self.logger.info(
                f"Incremental fetch page {page}/{max_pages}"
            )
            data = self.query_files(page=page, numperpage=numperpage)
            if data is None:
                break

            publishedfiles = data.get("publishedfiledetails", [])
            if not publishedfiles:
                break

            # Apply days filter
            if days > 0:
                publishedfiles = self._filter_by_days(publishedfiles, days)

            page_new = 0
            for item in publishedfiles:
                pid = str(item.get("publishedfileid", ""))
                if not pid:
                    continue
                if pid not in existing_set and pid not in new_ids:
                    new_ids.append(pid)
                    page_new += 1

            self.logger.info(
                f"Page {page}: {page_new} new mods out of "
                f"{len(publishedfiles)} results"
            )

            # If nothing new on this page, we've caught up
            if page_new == 0:
                self.logger.info(
                    "No new mods on this page — caught up with latest updates"
                )
                break

            total = data.get("total", 0)
            if total and page * numperpage >= total:
                break

        self.logger.info(
            f"Incremental mode: {len(new_ids)} new mods found"
        )
        return new_ids
