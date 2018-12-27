# -*- coding: utf-8 -*-
import logging
import xbmcaddon
from resources.lib import kodilogging

import requests
import urllib2


import hashlib
import hmac

import time
import re
import xbmc
import sys

from urllib import urlencode
from urllib import quote
from urlparse import parse_qsl

from datetime import datetime

import xbmcgui
import xbmcplugin

ADDON = xbmcaddon.Addon()
logger = logging.getLogger(ADDON.getAddonInfo('id'))
kodilogging.config()

#
# Globals
#
# Get the plugin url in plugin:// notation.
_url = sys.argv[0]
# Get the plugin handle as an integer number.
_handle = int(sys.argv[1])

session = requests.Session()


def _hotstarauth_key():
    def keygen(t):
        e = ""
        n = 0
        while len(t) > n:
            r = t[n] + t[n + 1]
            o = int(re.sub(r"[^a-f0-9]", "", r + "", re.IGNORECASE), 16)
            e += chr(o)
            n += 2

        return e

    start = int(time.time())
    expiry = start + 6000
    message = "st={}~exp={}~acl=/*".format(start, expiry)
    secret = keygen("05fc1a01cac94bc412fc53120775f9ee")
    signature = hmac.new(secret, message, digestmod=hashlib.sha256).hexdigest()
    return '{}~hmac={}'.format(message, signature)


_auth = _hotstarauth_key()

_GET_HEADERS = {
    "Origin": "https://ca.hotstar.com",
    "hotstarauth": _auth,
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.80 Safari/537.36",
    "x-country-code": "IN",
    "x-client-code": "LR",
    "x-platform-code": "PCTV",
    "Accept": "*/*",
    "Referer": "https://ca.hotstar.com/",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "x-dst-drm": "DASH/WIDEVINE",
}


def make_request(url, country_code=None):
    try:
        logger.info("Making request: {}, country_code: {}".format(url, country_code))
        headers = _GET_HEADERS
        if country_code is not None:
            headers['x-country-code'] = country_code

        response = session.get(url, headers=headers, cookies=session.cookies)
        data = response.json()
        if data.get('statusCodeValue') == 200:
            return data

        elif country_code is None:
            logger.debug('Falling back to CA country code for getting the data for {}'.format(url))
            return make_request(url, country_code='CA')

        else:
            raise Exception('Failed to fetch data for API!', url)

    except (urllib2.URLError, Exception) as e:
        logger.error("Failed to service request: {} -- {}".format(url, str(e)))


def _items(results):
    if 'assets' in results:
        return results['assets']['items']
    else:
        return results['items']


def _next_page(results):
    assets = results['assets'] if 'assets' in results else results
    return assets['nextOffsetURL'] if 'nextOffsetURL' in assets else None


def get_playback_url(url):
    data = make_request(url)
    if not data:
        return

    return data['body']['results']['item']['playbackUrl']


def list_program_details(title, uri):
    if not uri:
        return

    if '?' in uri:
        base_url, param_string = uri.split('?')
        params = dict(parse_qsl(param_string))
        if 'tas' in params and int(params['tas']) < 30:
            params['tas'] = 30
        uri = '{}?{}'.format(base_url, urlencode(params))

    data = make_request(uri)
    program = data['body']['results'].get('item')

    # Set plugin category. It is displayed in some skins as the name
    # of the current section.
    xbmcplugin.setPluginCategory(_handle, title)

    for item in data['body']['results']['trays']['items']:
        # {
        #   "title": "Episodes",
        #   "uri": "https://api.hotstar.com/o/v1/tray/g/1/detail?eid=1101&etid=2&tao=0&tas=20",
        #   "traySource": "CATALOG",
        #   "layoutType": "HORIZONTAL",
        #   "trayTypeId": 7002,
        #   "traySourceId": 100,
        #   "uqId": "1_2_1101"
        # },
        assets = item.get('assets')
        if not item.get('uri') or not (assets and assets.get('totalResults', 0)):
            continue

        item_title = item['title']
        content_id = program['contentId'] if program else ''
        description = program['description'] if program else 'N/A'
        genre = program.get('genre') if program else 'N/A'
        if item_title == 'Seasons':
            action = 'seasons'
        else:
            action = 'episodes'

        _add_directory_item(
            title,
            item_title,
            content_id,
            genre,
            description,
            item['uri'],
            action
        )

    # Add Search.
    _add_search_item()

    # Add a sort method for the virtual folder items (alphabetically, ignore articles)
    xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_NONE)

    # Finish creating a virtual folder.
    xbmcplugin.endOfDirectory(_handle)


def _get_data(url):
    data = make_request(url)
    return {
        'items': _items(data['body']['results']),
        'nextPage': _next_page(data['body']['results'])
    }


def list_seasons(title, url):
    # Set plugin category. It is displayed in some skins as the name
    # of the current section.
    xbmcplugin.setPluginCategory(_handle, title)
    # Get the list of videos in the category.
    result = _get_data(url)

    # Iterate through videos.
    for season in result['items']:
        # {
        #     "title": "Chapter 23",
        #     "categoryId": 2433,
        #     "contentId": 2482,
        #     "uri": "https://api.hotstar.com/o/v1/season/detail?id=1481&avsCategoryId=2433&offset=0&size=5",
        #     "assetType": "SEASON",
        #     "episodeCnt": 86,
        #     "seasonNo": 23,
        #     "showName": "Neeya Naana",
        #     "showId": 80,
        #     "showShortTitle": "Neeya Naana"
        # },

        base_url, param_string = season['uri'].split('?')
        params = dict(parse_qsl(param_string))
        params['size'] = 30
        season_uri = '{}?{}'.format(base_url, urlencode(params))

        _add_directory_item(
            title,
            season['title'],
            season['contentId'],
            None,
            None,
            season_uri,
            'episodes'
        )

    _add_next_page_and_search_item(result['nextPage'], 'seasons', title)

    # Add a sort method for the virtual folder items (alphabetically, ignore articles)
    xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_NONE)

    # Finish creating a virtual folder.
    xbmcplugin.endOfDirectory(_handle)


def _add_video_item(video):
    # Create a list item with a text label and a thumbnail image.
    episode_no = video.get('episodeNo')
    title = u'Episode {}: {}'.format(
        episode_no, video['title']
    ) if episode_no else video['title']
    list_item = xbmcgui.ListItem(label=title)

    # Set additional info for the list item.
    # 'mediatype' is needed for skin to display info for this ListItem correctly.
    episode_date = video.get('broadCastDate') or video.get('startDate')
    asset_type = video.get('assetType') or video.get('contentType')
    if asset_type != 'MOVIE' and episode_date:
        title = u'{} | {}'.format(datetime.fromtimestamp(episode_date).strftime('%b %d'), title)

    list_item.setInfo('video', {
        'title': title,
        'genre': video.get('genre'),
        'episode': episode_no,
        'season': video.get('seasonNo'),
        'plot': video['description'],
        'duration': video['duration'],
        'year': video.get('year', datetime.fromtimestamp(episode_date).year if episode_date else None),
        'date': datetime.fromtimestamp(episode_date).strftime('%d.%m.%Y') if episode_date else None,
        'mediatype': 'video',
    })

    # Set graphics (thumbnail, fanart, banner, poster, landscape etc.) for the list item.
    # Here we use the same image for all items for simplicity's sake.
    image = get_thumbnail_image(video['contentId'])
    list_item.setArt({
        'thumb': image,
        'icon': image,
        'fanart': image,
    })

    # Set 'IsPlayable' property to 'true'.
    # This is mandatory for playable items!
    list_item.setProperty('IsPlayable', 'true')

    # Create a URL for a plugin recursive call.
    # Example: plugin://plugin.video.example/?action=play&video=http:
    # //www.vidsplay.com/wp-content/uploads/2017/04/crab.mp4
    url = get_url(action='play', uri=video['playbackUri'])

    # Add the list item to a virtual Kodi folder.
    # is_folder = False means that this item won't open any sub-list.
    is_folder = False

    # Add our item to the Kodi virtual folder listing.
    xbmcplugin.addDirectoryItem(_handle, url, list_item, is_folder)


def list_episodes(title, uri):
    """
    Create the list of playable videos in the Kodi interface.
    """

    # Set plugin category. It is displayed in some skins as the name
    # of the current section.
    xbmcplugin.setPluginCategory(_handle, title)

    # Get the list of videos in the category.
    result = _get_data(uri)
    # Iterate through videos.
    for video in result['items']:
        # {
        #     "title": "Sakthi returns to India",
        #     "contentId": 1000036012,
        #     "uri": "https://api.hotstar.com/o/v1/episode/detail?id=80096&contentId=
        #     1000036012&offset=0&size=20&tao=0&tas=5",
        #     "description": "Saravanana and Meenakshi's oldest son, Sakthi, returns to
        #     India 25 years after his parents had left it. He wants to search for a bride,",
        #     "duration": 1332,
        #     "contentType": "EPISODE",
        #     "contentProvider": "Global Villagers",
        #     "cpDisplayName": "Global Villagers",
        #     "assetType": "EPISODE",
        #     "genre": [
        #         "Family"
        #     ],
        #     "lang": [
        #         "Tamil"
        #     ],
        #     "channelName": "Star Vijay",
        #     "seasonNo": 1,
        #     "episodeNo": 520,
        #     "premium": false,
        #     "live": false,
        #     "hboContent": false,
        #     "encrypted": false,
        #     "startDate": 1416649260,
        #     "endDate": 4127812200,
        #     "broadCastDate": 1382367600,
        #     "showName": "Saravanan Meenatchi",
        #     "showId": 99,
        #     "showShortTitle": "Saravanan Meenatchi",
        #     "seasonName": "Chapter 1",
        #     "playbackUri": "https://api.hotstar.com/h/v1/play?contentId=1000036012",
        #     "contentDownloadable": false
        # },
        _add_video_item(video)

    _add_next_page_and_search_item(result['nextPage'], 'episodes', title)

    # Add a sort method for the virtual folder items (alphabetically, ignore articles)
    xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_NONE)

    # Finish creating a virtual folder.
    xbmcplugin.endOfDirectory(_handle)


def get_thumbnail_image(content_id):
    content_id = str(content_id)
    return 'https://secure-media2.hotstar.com/t_web_hs_3x/r1/thumbs/PCTV/'\
        '{contentIdLastTwo}/{contentId}/PCTV-{contentId}-hcdl.jpg'.format(
            contentIdLastTwo=content_id[2:], contentId=content_id
        )


def _add_next_page_and_search_item(uri, action, original_title):
    if uri:
        title = '| Next Page >>>'
        list_item = xbmcgui.ListItem(label=title)
        list_item.setInfo('video', {
            'mediatype': 'video'
        })

        # Create a URL for a plugin recursive call.
        # Example: plugin://plugin.video.example/?action=listing&category=Animals
        url = get_url(action=action, uri=uri, title=original_title)

        # is_folder = True means that this item opens a sub-list of lower level items.
        is_folder = True

        # Add our item to the Kodi virtual folder listing.
        xbmcplugin.addDirectoryItem(_handle, url, list_item, is_folder)

    # Add Search item.
    _add_search_item()


def _add_directory_item(parent_title, title, content_id, genre, description, uri, action):
    # Create a list item with a text label and a thumbnail image.
    list_item = xbmcgui.ListItem(label=title)

    # Set graphics (thumbnail, fanart, banner, poster, landscape etc.) for the list item.
    # Here we use the same image for all items for simplicity's sake.
    # In a real-life plugin you need to set each image accordingly.
    image = get_thumbnail_image(content_id)
    list_item.setArt({
        'thumb': image,
        'icon': image,
        'fanart': image
    })

    # Set additional info for the list item.
    # Here we use a category name for both properties for for simplicity's sake.
    # setInfo allows to set various information for an item.
    # For available properties see the following link:
    # https://codedocs.xyz/xbmc/xbmc/group__python__xbmcgui__listitem.html#ga0b71166869bda87ad744942888fb5f14
    # 'mediatype' is needed for a skin to display info for this ListItem correctly.
    list_item.setInfo('video', {
        'count': content_id,
        'title': title,
        'genre': genre,
        'plot': description,
        'mediatype': 'video'
    })

    # Create a URL for a plugin recursive call.
    # Example: plugin://plugin.video.example/?action=listing&category=Animals
    url = get_url(action=action, uri=uri, title='{}/{}'.format(parent_title, title) if parent_title else title)

    # is_folder = True means that this item opens a sub-list of lower level items.
    is_folder = True

    # Add our item to the Kodi virtual folder listing.
    xbmcplugin.addDirectoryItem(_handle, url, list_item, is_folder)


def list_programs(channel_name, uri):
    """
    List the programs under each channel.
    """
    # Set plugin category. It is displayed in some skins as the name
    # of the current section.
    xbmcplugin.setPluginCategory(_handle, channel_name)
    # Get the list of videos in the category.
    result = _get_data(uri)
    # Iterate through videos.
    for program in result['items']:
        # {
        #     "title": "Raja Rani",
        #     "categoryId": 14064,
        #     "contentId": 14230,
        #     "uri": "https://api.hotstar.com/o/v1/show/detail?id=
        #     1101&avsCategoryId=14064&contentId=14230&offset=0&size=20&tao=0&tas=5",
        #     "description": "Due to certain circumstances, Karthik marries the maid of his family,",
        #     "assetType": "SHOW",
        #     "genre": [
        #         "Family"
        #     ],
        #     "lang": [
        #         "Tamil"
        #     ],
        #     "channelName": "Star Vijay",
        #     "episodeCnt": 407,
        #     "premium": false
        # },
        _add_directory_item(
            channel_name,
            program['title'],
            program['contentId'],
            program.get('genre'),
            program['description'],
            program['uri'],
            'program_details'
        )

    _add_next_page_and_search_item(result['nextPage'], 'programs', channel_name)

    # Add a sort method for the virtual folder items (alphabetically, ignore articles)
    xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_LABEL)

    # Finish creating a virtual folder.
    xbmcplugin.endOfDirectory(_handle)


def list_channels():
    """
    Create the list of video categories in the Kodi interface.
    """
    # Set plugin category. It is displayed in some skins as the name
    # of the current section.
    xbmcplugin.setPluginCategory(_handle, 'Channels')

    # Set plugin content. It allows Kodi to select appropriate views
    # for this type of content -- didn't use this since it's not working well
    # with the video item.
    # xbmcplugin.setContent(_handle, 'videos')

    # Get channels.
    result = _get_data('https://api.hotstar.com/o/v1/channel/list?perPage=1000')
    # Iterate through categories
    for channel in result['items']:
        # Channel JSON structure.
        # {
        #     "title": "Star Vijay",
        #     "categoryId": 748,
        #     "contentId": 824,
        #     "uri": "https://api.hotstar.com/o/v1/channel/detail?id=12&avsCategoryId=748&contentId=824&offset=0&size=20
        #     &pageNo=1&perPage=20",
        #     "description": "A Tamil general entertainment channel with family drama, comedy and reality shows.",
        #     "assetType": "CHANNEL",
        #     "genre": [
        #         "LiveTV"
        #     ],
        #     "lang": [
        #         "Tamil"
        #     ],
        #     "showCnt": 137
        # },
        #
        _add_directory_item(
            '',
            channel['title'],
            channel['contentId'],
            channel.get('genre'),
            channel['description'],
            channel['uri'],
            'programs'
        )

    # Add Sports
    _add_directory_item(
        '',
        'Hotstar Sports',
        821,
        'Sports',
        'Sports',
        'https://api.hotstar.com/o/v1/page/1327?tas=30',
        'program_details'
    )
    # Movies
    _add_directory_item(
        '',
        'Hotstar Movies',
        821,
        'Movies',
        'Movies',
        'https://api.hotstar.com/o/v1/page/1328?tas=30',
        'program_details'
    )
    # https://api.hotstar.com/o/v1/page/1329?offset=0&size=20&tao=0&tas=20
    _add_directory_item(
        '',
        'Hotstar TV',
        821,
        'TV',
        'TV',
        'https://api.hotstar.com/o/v1/page/1329?tas=30',
        'program_details'
    )
    # # https://api.hotstar.com/o/v1/page/1329?offset=0&size=20&tao=0&tas=20
    # _add_directory_item(
    #     '',
    #     'Hotstar TV',
    #     821,
    #     'TV',
    #     'TV',
    #     'https://api.hotstar.com/o/v1/page/1329?tas=30',
    #     'program_details'
    # )

    _add_search_item()

    # Add a sort method for the virtual folder items (alphabetically, ignore articles)
    xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_LABEL)

    # Finish creating a virtual folder.
    xbmcplugin.endOfDirectory(_handle)


def get_url(**kwargs):
    """
    Create a URL for calling the plugin recursively from the given set of keyword arguments.

    :param kwargs: "argument=value" pairs
    :type kwargs: dict
    :return: plugin call URL
    :rtype: str
    """
    return '{0}?{1}'.format(_url, urlencode(kwargs))


def play_video(path):
    """
    Play a video by the provided path.

    :param path: Fully-qualified video URL
    :type path: str
    """
    # Create a playable item with a path to play.
    play_item = xbmcgui.ListItem(path=get_playback_url(path))
    # Pass the item to the Kodi player.
    xbmcplugin.setResolvedUrl(_handle, True, listitem=play_item)


def get_user_input():
    kb = xbmc.Keyboard('', 'Search for Movies/TV Shows/Trailers/Videos in all languages')
    kb.doModal()  # Onscreen keyboard appears
    if not kb.isConfirmed():
        return

    # User input
    return kb.getText()


def _add_search_item():
    _add_directory_item('', '| Search', 1, 'Search', 'Search', '', 'search')


def list_search():
    query = get_user_input()
    if not query:
        return []

    # Set plugin category. It is displayed in some skins as the name
    # of the current section.
    xbmcplugin.setPluginCategory(_handle, 'Search/{}'.format(query))

    url = 'https://api.hotstar.com/s/v1/scout?q={}&perPage=10'.format(quote(query))
    data = make_request(url)
    for item in data['body']['results']['items']:
        asset_type = item.get('assetType')
        if asset_type in ['CHANNEL', 'SHOW']:
            _add_directory_item(
                'Search/{}'.format(query),
                item['title'],
                item['contentId'],
                item.get('genre'),
                item['description'],
                item['uri'],
                'programs' if asset_type == 'CHANNEL' else 'program_details'
            )

        elif asset_type in ['MOVIE', 'VIDEO']:
            _add_video_item(item)

    # Add a sort method for the virtual folder items (alphabetically, ignore articles)
    xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.endOfDirectory(_handle)


def router(paramstring):
    """
    Router function that calls other functions
    depending on the provided paramstring

    :param paramstring: URL encoded plugin paramstring
    :type paramstring: str
    """
    # Parse a URL-encoded paramstring to the dictionary of
    # {<parameter>: <value>} elements
    params = dict(parse_qsl(paramstring))
    # Check the parameters passed to the plugin
    logger.info('Handling route params -- {}'.format(params))
    if params:
        title = params.get('title')
        uri = params.get('uri', None)
        action = params['action']
        if action == 'programs':
            list_programs(title, uri)

        elif action == 'program_details':
            list_program_details(title, uri)

        elif action == 'episodes':
            list_episodes(title, uri)

        elif action == 'seasons':
            list_seasons(title, uri)

        elif action == 'play':
            # Play a video from a provided URL.
            play_video(uri)

        elif action == 'search':
            list_search()

        else:
            # If the provided paramstring does not contain a supported action
            # we raise an exception. This helps to catch coding errors,
            # e.g. typos in action names.
            raise ValueError('Invalid paramstring: {0}!'.format(paramstring))

    else:
        # List all the channels at the base level.
        list_channels()


def run():
    # Call the router function and pass the plugin call parameters to it.
    # We use string slicing to trim the leading '?' from the plugin call paramstring
    router(sys.argv[2][1:])
