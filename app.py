from typing import Any, Union

from flask import Flask, redirect, request, url_for, session
from dotenv import load_dotenv
from datetime import datetime, timedelta, date
import numpy as np
import requests
import json
import os
import sys

from werkzeug import Response

load_dotenv()  # load the environment variables
CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI')  # our local host
USER_ID = os.getenv('SPOTIFY_USER_ID')

SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
MY_FOLLOWED_ARTISTS_URL = 'https://api.spotify.com/v1/me/following?type=artist'

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')


# tokens for starting a new session on different routes
def get_tokens():
    with open('tokens.json', 'r') as openfile:
        tokens = json.load(openfile)
    return tokens


# getting track uris for adding to playlist route
def get_tracks():
    with open('track_uris.json', 'r') as openfile:
        track_uris = json.load(openfile)
    return track_uris


# this route will request authorisation from the user to access their information
@app.route('/')
def request_auth():
    # Scopes enable your application to access specific functionality (e.g. read a playlist, modify your library or
    # just streaming) on behalf of a user
    scope = 'user-top-read playlist-modify-public playlist-modify-private user-follow-read'
    return redirect(
        f'https://accounts.spotify.com/authorize?response_type=code&client_id={CLIENT_ID}&scope={scope}&redirect_uri={REDIRECT_URI}')


# after user authorisation the user will be taken to this route. Once the user accepted your request, then your app is
# ready to exchange the authorization code for an Access Token. It will do this by making a POST request to the
# /api/token endpoint
@app.route('/callback')
def request_tokens():
    code = request.args.get('code')

    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    r = requests.post(SPOTIFY_TOKEN_URL, data=payload)
    response = r.json()

    tokens = {
        'access_token': response['access_token'],
        'refresh_token': response['refresh_token'],
        'expires_in': response['expires_in']
    }

    # saving tokens to a file for easier access through different routes
    with open('tokens.json', 'w') as outfile:
        json.dump(tokens, outfile)

    return redirect(url_for('get_artists'))  # next route


@app.route('/get_artists')
def get_artists():
    with open('tokens.json', 'r') as openfile:
        tokens = json.load(openfile)

    headers = {'Authorization': f'Bearer {tokens["access_token"]}'}
    r = requests.get(MY_FOLLOWED_ARTISTS_URL, headers=headers)
    response = r.json()

    # we want to get artists ids for you use in the next route when accessing albums
    # we will append them to this list
    artist_ids = []
    artists = response['artists']['items']
    for artist in artists:
        artist_ids.append(artist['id'])

    # if a user follows multiple artists we need to parse through multiples pages
    # multiple pages of artists info are indicated by 'next' in the json
    while response['artists']['next']:
        nex_page_uri = response['artists']['next']
        r = requests.get(nex_page_uri, headers=headers)
        response = r.json()
        for artist in response['artists']['items']:
            artist_ids.append(artist['id'])

    session['artist_ids'] = artist_ids  # session allows you to store information specific to a user from one request
    # to the next

    return redirect(url_for('get_albums'))


@app.route('/get_albums')
def get_albums():
    # getting access tokens
    tokens = get_tokens()

    # retrieving artists IDs from session in previous route
    artist_ids = session['artist_ids']
    album_ids = []  #
    album_names = {}

    today = datetime.now()
    number_weeks = timedelta(weeks=4)
    time_frame = (today - number_weeks).date()  # time frame for if an album is considered new to us

    for id in artist_ids:
        uri = f'https://api.spotify.com/v1/artists/{id}/albums?include_groups=album,single&country=US'
        headers = {'Authorization': f'Bearer {tokens["access_token"]}'}
        r = requests.get(uri, headers=headers)
        response = r.json()

        # loop through albums and select the new ones
        albums = response['items']
        for album in albums:
            try:
                release_date = datetime.strptime(album['release_date'], '%Y-%m-%d')
                album_name = album['name']
                artist_name = album['artists'][0]['name']

                # checking release date against our time frame
                if release_date.date() > time_frame:
                    # checking for duplicates in album
                    if album_name not in album_names or artist_name != album_names[album_name]:
                        album_ids.append(album['id'])
                        album_names[album_name] = artist_name

            except ValueError:
                print(f'Release date found with format: {album["release_date"]}')

    session['album_ids'] = album_ids
    return redirect(url_for('get_tracks'))


# getting each albums tracks
@app.route('/get_tracks')
def get_tracks():
    tokens = get_tokens()
    album_ids = session['album_ids']

    track_uris = []

    for id in album_ids:  # tracks in each album
        uri = f'https://api.spotify.com/v1/albums/{id}/tracks'
        headers = {'Authorization': f'Bearer {tokens["access_token"]}'}
        r = requests.get(uri, headers=headers)
        response = r.json()

        for track in response['items']:
            track_uris.append(track)

    print('Received tracks')
    # storing track uris in json file because there is a lot of information. Too much for session
    uri_dictionary = {'uris': track_uris}
    print(type(uri_dictionary))
    with open('track_uris.json', 'w') as outfile:
        json.dump(uri_dictionary, outfile)

    return redirect(url_for('create_playlist'))


@app.route('/create_playlist')
def create_playlist():
    tokens = get_tokens()
    current_date = (date.today()).strftime('%m-%d-%Y')
    playlist_name = f"Vibe Check - {current_date}"

    uri = f'https://api.spotify.com/v1/users/{USER_ID}/playlists'
    headers = {'Authorization': f'Bearer {tokens["access_token"]}', 'Content-Type': 'application/json'}
    payload = {'name': playlist_name}
    r = requests.post(uri, headers=headers, data=json.dumps(payload))
    response = r.json()

    session['playlist_id'] = response['id']
    session['playlist_url'] = response['external_urls']['spotify']

    print('Created playlist')
    return redirect(url_for('add_tracks'))


# adding songs to playlist
@app.route('/add_tracks')
def add_tracks():
    tokens = get_tokens()
    print(type(tokens))
    playlist_id = session['playlist_id']
    track_uris = get_tracks()
    print(type(track_uris))
    track_list = track_uris['uris']
    number_of_tracks = len(track_list)

    if number_of_tracks > 200:
        three_split = np.array_split(track_list, 3)
        for lst in three_split:
            uri = f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks'
            headers = {'Authorization': f'Bearer {tokens["access_token"]}', 'Content-Type': 'application/json'}
            payload = {'uris': list(lst)}
            r = requests.post(uri, headers=headers, data=json.dumps(payload))
            response = r.json()

    elif number_of_tracks > 100:
        two_split = np.array_split(track_list, 2)
        for lst in two_split:
            uri = f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks'
            headers = {'Authorization': f'Bearer {tokens["access_token"]}', 'Content-Type': 'application/json'}
            payload = {'uris': list(lst)}
            r = requests.post(uri, headers=headers, data=json.dumps(payload))
            response = r.json()

    else:
        uri = f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks'
        headers = {'Authorization': f'Bearer {tokens["access_token"]}', 'Content-Type': 'application/json'}
        payload = {'uris': 'track_list'}
        r = requests.post(uri, headers=headers, data=json.dumps(payload))
        response = r.json()

    print('Added tracks to playlist!')

    return redirect(session['playlist_url'])
