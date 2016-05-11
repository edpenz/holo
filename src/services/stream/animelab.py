import calendar
import locale
import re
from datetime import datetime
from logging import debug, warning, error

from data.models import Episode, UnprocessedStream
from .. import AbstractServiceHandler


class ServiceHandler(AbstractServiceHandler):
    _show_link_url = "http://www.animelab.com/shows/{key}"
    _show_link_url_id_re = re.compile("animelab.com/shows/([\w-]+)", re.I)

    _episode_link_url = "http://www.animelab.com/player/{episode}"

    _list_seasonal_shows_url = "http://www.animelab.com/api/simulcasts?limit=100&page={page}"
    _list_show_episodes_url = "http://www.animelab.com/api/videoentries/show/{id}?limit=30&page={page}"
    _list_aired_episodes_url = "http://www.animelab.com/api/simulcasts/episodes/latest?limit=10&page={page}"

    def __init__(self):
        super().__init__("animelab", "AnimeLab", False)

    # Modify all requests to check for and apply proxy
    def request(self, url, proxy=None, **kwargs):
        if ":" in self.config.get("proxy", ""):
            proxy = tuple(self.config["proxy"].split(":"))

        lang = locale.getdefaultlocale()[0]
        if proxy is None and "AU" not in lang and "NZ" not in lang:
            warning("AnimeLab requires an AU/NZ IP, but no proxy was supplied")

        return super().request(url, proxy=proxy, **kwargs)

    # Episodes are usually delayed at least several hours, so the utility of this will be limited
    def get_latest_episode(self, stream, **kwargs):
        page_index = 0
        page_url = self._list_aired_episodes_url.format(page=page_index)

        page_json = self.request(page_url, json=True, **kwargs)
        if page_json is None:
            error("Failed to get recently aired shows list")
            return None

        for episode_json in page_json["list"]:
            episode_show_key = episode_json["showSlug"]
            if stream.show_key == episode_show_key:
                return self._episode_from_json(episode_json)

        # TODO Use show-specific API if not found in recently aired list
        warning("Skipped checking show-specific episode list")

        return None

    def _episode_from_json(self, episode_json):
        episode_number = int(episode_json["episodeNumber"])
        episode_name = episode_json["name"]
        episode_slug = episode_json["slug"]
        episode_link_url = self._episode_link_url.format(episode=episode_slug)
        # TODO Given release date is unreliable so ignore it for now
        return Episode(episode_number, episode_name, episode_link_url, datetime.utcnow())

    def get_stream_info(self, stream, **kwargs):
        # TODO Figure out what info might be missing.
        return None  # or the updated stream

    def get_seasonal_streams(self, year=None, season=None, **kwargs):
        found_streams = list()

        # Perform API request for show list
        page_index = 0
        page_url = self._list_seasonal_shows_url.format(page=page_index)

        page_json = self.request(page_url, json=True, **kwargs)
        if page_json is None:
            error("Failed to get seasonal shows list")
            return found_streams

        # Extract streams from response JSON
        for show_json in page_json["list"]:
            if not self._is_airing_during_season(show_json, year, season):
                continue

            stream = self._stream_from_json(show_json)
            found_streams += [stream]

        # TODO Handle multiple pages of results.
        remaining_page_count = page_json["totalPageCount"] - 1
        if remaining_page_count > 0:
            warning("Skipped {} pages of results".format(remaining_page_count))

        return found_streams

    def _stream_from_json(self, show_json):
        show_key = show_json["slug"]
        show_name = show_json["name"]  # Could also use "originalName"

        debug("Found show {}: \"{}\"".format(show_key, show_name))

        return UnprocessedStream(self.key, show_key, None, show_name, 0, 0)

    @staticmethod
    def _is_airing_during_season(show_json, year, season):
        if year is None or season is None:
            return True

        stream_start_timestamp = show_json["simulcastStartDate"] / 1000
        stream_end_timestamp = show_json["simulcastEndDate"] / 1000

        # TODO Confirm the appropriate values for the season parameter
        midseason_dates = {
            'winter': datetime(year, 2, 15),
            'spring': datetime(year, 5, 15),
            'summer': datetime(year, 8, 15),
            'autumn': datetime(year, 11, 15),
            'fall': datetime(year, 11, 15)
        }

        midseason_timestamp = calendar.timegm(midseason_dates[season].utctimetuple())

        return stream_start_timestamp < midseason_timestamp < stream_end_timestamp

    def get_stream_link(self, stream):
        return self._show_link_url.format(key=stream.show_key)

    def extract_show_key(self, url):
        match = self._show_link_url_id_re.search(url)
        return match.group(1) if match else None
