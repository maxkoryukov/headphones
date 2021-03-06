#  This file is part of Headphones.
#
#  Headphones is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Headphones is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Headphones.  If not, see <http://www.gnu.org/licenses/>.

# NZBGet support added by CurlyMo <curlymoo1@gmail.com> as a part of XBian - XBMC on the Raspberry Pi

from operator import itemgetter
import threading
import hashlib
import random
import urllib
import json
import time
import cgi
import sys
import urllib2

import os
import re
from headphones import logger, searcher, db, importer, mb, lastfm, librarysync, helpers, notifiers
from headphones.helpers import today, clean_name
from mako.lookup import TemplateLookup
from mako import exceptions
import headphones
import cherrypy

try:
    # pylint:disable=E0611
    # ignore this error because we are catching the ImportError
    from collections import OrderedDict
    # pylint:enable=E0611
except ImportError:
    # Python 2.6.x fallback, from libs
    from ordereddict import OrderedDict

# will be useful for translation


def _(x):
    return x


def serve_template(templatename, **kwargs):
    interface_dir = os.path.join(str(headphones.PROG_DIR), 'data/interfaces/')
    template_dir = os.path.join(str(interface_dir), headphones.CONFIG.INTERFACE)

    _hplookup = TemplateLookup(directories=[template_dir])

    try:
        template = _hplookup.get_template(templatename)
        return template.render(**kwargs)
    except:
        return exceptions.html_error_template().render()


class WebInterface(object):

    @cherrypy.expose
    def index(self):
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def home(self):
        myDB = db.DBConnection()
        artists = myDB.select('SELECT * from artists order by ArtistSortName COLLATE NOCASE')
        return serve_template(templatename="index.html", title="Home", artists=artists)

    @cherrypy.expose
    def artistPage(self, ArtistID):
        myDB = db.DBConnection()
        artist = myDB.action('SELECT * FROM artists WHERE ArtistID=?', [ArtistID]).fetchone()

        # Don't redirect to the artist page until it has the bare minimum info inserted
        # Redirect to the home page if we still can't get it after 5 seconds
        retry = 0

        while not artist and retry < 5:
            time.sleep(1)
            artist = myDB.action('SELECT * FROM artists WHERE ArtistID=?', [ArtistID]).fetchone()
            retry += 1

        if not artist:
            raise cherrypy.HTTPRedirect("home")

        albums = myDB.select('SELECT * from albums WHERE ArtistID=? order by ReleaseDate DESC',
                             [ArtistID])

        # Serve the extras up as a dict to make things easier for new templates (append new extras to the end)
        extras_list = headphones.POSSIBLE_EXTRAS
        if artist['Extras']:
            artist_extras = map(int, artist['Extras'].split(','))
        else:
            artist_extras = []

        extras_dict = OrderedDict()

        i = 1
        for extra in extras_list:
            if i in artist_extras:
                extras_dict[extra] = "checked"
            else:
                extras_dict[extra] = ""
            i += 1

        return serve_template(templatename="artist.html", title=artist['ArtistName'], artist=artist,
                              albums=albums, extras=extras_dict)

    @cherrypy.expose
    def albumPage(self, AlbumID):
        myDB = db.DBConnection()
        album = myDB.action('SELECT * from albums WHERE AlbumID=?', [AlbumID]).fetchone()

        retry = 0
        while retry < 5:
            if not album:
                time.sleep(1)
                album = myDB.action('SELECT * from albums WHERE AlbumID=?', [AlbumID]).fetchone()
                retry += 1
            else:
                break

        if not album:
            raise cherrypy.HTTPRedirect("home")

        tracks = myDB.select(
            'SELECT * from tracks WHERE AlbumID=? ORDER BY CAST(TrackNumber AS INTEGER)', [AlbumID])
        description = myDB.action('SELECT * from descriptions WHERE ReleaseGroupID=?',
                                  [AlbumID]).fetchone()

        if not album['ArtistName']:
            title = ' - '
        else:
            title = album['ArtistName'] + ' - '
        if not album['AlbumTitle']:
            title = title + ""
        else:
            title = title + album['AlbumTitle']
        return serve_template(templatename="album.html", title=title, album=album, tracks=tracks,
                              description=description)

    @cherrypy.expose
    def search(self, name, type):
        if len(name) == 0:
            raise cherrypy.HTTPRedirect("home")
        if type == 'artist':
            searchresults = mb.findArtist(name, limit=100)
        elif type == 'album':
            searchresults = mb.findRelease(name, limit=100)
        else:
            searchresults = mb.findSeries(name, limit=100)
        return serve_template(templatename="searchresults.html",
                              title='Search Results for: "' + cgi.escape(name) + '"',
                              searchresults=searchresults, name=cgi.escape(name), type=type)

    @cherrypy.expose
    def addArtist(self, artistid):
        thread = threading.Thread(target=importer.addArtisttoDB, args=[artistid])
        thread.start()
        thread.join(1)
        raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % artistid)

    @cherrypy.expose
    def addSeries(self, seriesid):
        thread = threading.Thread(target=importer.addArtisttoDB,
                                  args=[seriesid, False, False, "series"])
        thread.start()
        thread.join(1)
        raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % seriesid)

    @cherrypy.expose
    def getExtras(self, ArtistID, newstyle=False, **kwargs):
        # if calling this function without the newstyle, they're using the old format
        # which doesn't separate extras, so we'll grab all of them
        #
        # If they are, we need to convert kwargs to string format
        if not newstyle:
            extras = "1,2,3,4,5,6,7,8,9,10,11,12,13,14"
        else:
            temp_extras_list = []
            i = 1
            for extra in headphones.POSSIBLE_EXTRAS:
                if extra in kwargs:
                    temp_extras_list.append(i)
                i += 1
            extras = ','.join(str(n) for n in temp_extras_list)

        myDB = db.DBConnection()
        controlValueDict = {'ArtistID': ArtistID}
        newValueDict = {'IncludeExtras': 1,
                        'Extras': extras}
        myDB.upsert("artists", newValueDict, controlValueDict)
        thread = threading.Thread(target=importer.addArtisttoDB, args=[ArtistID, True, False])
        thread.start()
        thread.join(1)
        raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % ArtistID)

    @cherrypy.expose
    def removeExtras(self, ArtistID, ArtistName):
        myDB = db.DBConnection()
        controlValueDict = {'ArtistID': ArtistID}
        newValueDict = {'IncludeExtras': 0}
        myDB.upsert("artists", newValueDict, controlValueDict)
        extraalbums = myDB.select(
            'SELECT AlbumID from albums WHERE ArtistID=? AND Status="Skipped" AND Type!="Album"',
            [ArtistID])
        for album in extraalbums:
            myDB.action('DELETE from tracks WHERE ArtistID=? AND AlbumID=?',
                        [ArtistID, album['AlbumID']])
            myDB.action('DELETE from albums WHERE ArtistID=? AND AlbumID=?',
                        [ArtistID, album['AlbumID']])
            myDB.action('DELETE from allalbums WHERE ArtistID=? AND AlbumID=?',
                        [ArtistID, album['AlbumID']])
            myDB.action('DELETE from alltracks WHERE ArtistID=? AND AlbumID=?',
                        [ArtistID, album['AlbumID']])
            myDB.action('DELETE from releases WHERE ReleaseGroupID=?', [album['AlbumID']])
            from headphones import cache
            c = cache.Cache()
            c.remove_from_cache(AlbumID=album['AlbumID'])
        importer.finalize_update(ArtistID, ArtistName)
        raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % ArtistID)

    @cherrypy.expose
    def pauseArtist(self, ArtistID):
        logger.info(u"Pausing artist: " + ArtistID)
        myDB = db.DBConnection()
        controlValueDict = {'ArtistID': ArtistID}
        newValueDict = {'Status': 'Paused'}
        myDB.upsert("artists", newValueDict, controlValueDict)
        raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % ArtistID)

    @cherrypy.expose
    def resumeArtist(self, ArtistID):
        logger.info(u"Resuming artist: " + ArtistID)
        myDB = db.DBConnection()
        controlValueDict = {'ArtistID': ArtistID}
        newValueDict = {'Status': 'Active'}
        myDB.upsert("artists", newValueDict, controlValueDict)
        raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % ArtistID)

    def removeArtist(self, ArtistID):
        myDB = db.DBConnection()
        namecheck = myDB.select('SELECT ArtistName from artists where ArtistID=?', [ArtistID])
        for name in namecheck:
            artistname = name['ArtistName']
        logger.info(u"Deleting all traces of artist: " + artistname)
        myDB.action('DELETE from artists WHERE ArtistID=?', [ArtistID])

        from headphones import cache
        c = cache.Cache()

        rgids = myDB.select(
            'SELECT AlbumID FROM albums WHERE ArtistID=? UNION SELECT AlbumID FROM allalbums WHERE ArtistID=?',
            [ArtistID, ArtistID])
        for rgid in rgids:
            albumid = rgid['AlbumID']
            myDB.action('DELETE from releases WHERE ReleaseGroupID=?', [albumid])
            myDB.action('DELETE from have WHERE Matched=?', [albumid])
            c.remove_from_cache(AlbumID=albumid)
            myDB.action('DELETE from descriptions WHERE ReleaseGroupID=?', [albumid])

        myDB.action('DELETE from albums WHERE ArtistID=?', [ArtistID])
        myDB.action('DELETE from tracks WHERE ArtistID=?', [ArtistID])

        myDB.action('DELETE from allalbums WHERE ArtistID=?', [ArtistID])
        myDB.action('DELETE from alltracks WHERE ArtistID=?', [ArtistID])
        myDB.action('DELETE from have WHERE ArtistName=?', [artistname])
        c.remove_from_cache(ArtistID=ArtistID)
        myDB.action('DELETE from descriptions WHERE ArtistID=?', [ArtistID])
        myDB.action('INSERT OR REPLACE into blacklist VALUES (?)', [ArtistID])

    @cherrypy.expose
    def deleteArtist(self, ArtistID):
        self.removeArtist(ArtistID)
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def scanArtist(self, ArtistID):

        myDB = db.DBConnection()
        artist_name = myDB.select('SELECT DISTINCT ArtistName FROM artists WHERE ArtistID=?',
            [ArtistID])[0][0]

        logger.info(u"Scanning artist: %s", artist_name)

        full_folder_format = headphones.CONFIG.FOLDER_FORMAT
        folder_format = re.findall(r'(.*?[Aa]rtist?)\.*', full_folder_format)[0]

        acceptable_formats = ["$artist", "$sortartist", "$first/$artist", "$first/$sortartist"]

        if not folder_format.lower() in acceptable_formats:
            logger.info(
                "Can't determine the artist folder from the configured folder_format. Not scanning")
            return

        # Format the folder to match the settings
        artist = artist_name.replace('/', '_')

        if headphones.CONFIG.FILE_UNDERSCORES:
            artist = artist.replace(' ', '_')

        if artist.startswith('The '):
            sortname = artist[4:] + ", The"
        else:
            sortname = artist

        if sortname[0].isdigit():
            firstchar = u'0-9'
        else:
            firstchar = sortname[0]

        values = {'$Artist': artist,
                  '$SortArtist': sortname,
                  '$First': firstchar.upper(),
                  '$artist': artist.lower(),
                  '$sortartist': sortname.lower(),
                  '$first': firstchar.lower(),
                  }

        folder = helpers.replace_all(folder_format.strip(), values, normalize=True)

        folder = helpers.replace_illegal_chars(folder, type="folder")
        folder = folder.replace('./', '_/').replace('/.', '/_')

        if folder.endswith('.'):
            folder = folder[:-1] + '_'

        if folder.startswith('.'):
            folder = '_' + folder[1:]

        dirs = []
        if headphones.CONFIG.MUSIC_DIR:
            dirs.append(headphones.CONFIG.MUSIC_DIR)
        if headphones.CONFIG.DESTINATION_DIR:
            dirs.append(headphones.CONFIG.DESTINATION_DIR)
        if headphones.CONFIG.LOSSLESS_DESTINATION_DIR:
            dirs.append(headphones.CONFIG.LOSSLESS_DESTINATION_DIR)

        dirs = set(dirs)

        for dir in dirs:
            artistfolder = os.path.join(dir, folder)
            if not os.path.isdir(artistfolder.encode(headphones.SYS_ENCODING)):
                logger.debug("Cannot find directory: " + artistfolder)
                continue
            threading.Thread(target=librarysync.libraryScan,
                             kwargs={"dir": artistfolder, "artistScan": True, "ArtistID": ArtistID,
                                     "ArtistName": artist_name}).start()
        raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % ArtistID)

    @cherrypy.expose
    def deleteEmptyArtists(self):
        logger.info(u"Deleting all empty artists")
        myDB = db.DBConnection()
        emptyArtistIDs = [row['ArtistID'] for row in
                          myDB.select("SELECT ArtistID FROM artists WHERE LatestAlbum IS NULL")]
        for ArtistID in emptyArtistIDs:
            self.removeArtist(ArtistID)

    @cherrypy.expose
    def refreshArtist(self, ArtistID):
        thread = threading.Thread(target=importer.addArtisttoDB, args=[ArtistID, False, True])
        thread.start()
        thread.join(1)
        raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % ArtistID)

    @cherrypy.expose
    def markAlbums(self, ArtistID=None, action=None, **args):
        myDB = db.DBConnection()
        if action == 'WantedNew' or action == 'WantedLossless':
            newaction = 'Wanted'
        else:
            newaction = action
        for mbid in args:
            logger.info("Marking %s as %s" % (mbid, newaction))
            controlValueDict = {'AlbumID': mbid}
            newValueDict = {'Status': newaction}
            myDB.upsert("albums", newValueDict, controlValueDict)
            if action == 'Wanted':
                searcher.searchforalbum(mbid, new=False)
            if action == 'WantedNew':
                searcher.searchforalbum(mbid, new=True)
            if action == 'WantedLossless':
                searcher.searchforalbum(mbid, lossless=True)
            if ArtistID:
                ArtistIDT = ArtistID
            else:
                ArtistIDT = \
                myDB.action('SELECT ArtistID FROM albums WHERE AlbumID=?', [mbid]).fetchone()[0]
            myDB.action(
                'UPDATE artists SET TotalTracks=(SELECT COUNT(*) FROM tracks WHERE ArtistID = ? AND AlbumTitle IN (SELECT AlbumTitle FROM albums WHERE Status != "Ignored")) WHERE ArtistID = ?',
                [ArtistIDT, ArtistIDT])
        if ArtistID:
            raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % ArtistID)
        else:
            raise cherrypy.HTTPRedirect("upcoming")

    @cherrypy.expose
    def addArtists(self, action=None, **args):
        if action == "add":
            threading.Thread(target=importer.artistlist_to_mbids, args=[args, True]).start()
        if action == "ignore":
            myDB = db.DBConnection()
            for artist in args:
                myDB.action('DELETE FROM newartists WHERE ArtistName=?',
                            [artist.decode(headphones.SYS_ENCODING, 'replace')])
                myDB.action('UPDATE have SET Matched="Ignored" WHERE ArtistName=?',
                            [artist.decode(headphones.SYS_ENCODING, 'replace')])
                logger.info("Artist %s removed from new artist list and set to ignored" % artist)
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def queueAlbum(self, AlbumID, ArtistID=None, new=False, redirect=None, lossless=False):
        logger.info(u"Marking album: " + AlbumID + " as wanted...")
        myDB = db.DBConnection()
        controlValueDict = {'AlbumID': AlbumID}
        if lossless:
            newValueDict = {'Status': 'Wanted Lossless'}
            logger.info("...lossless only!")
        else:
            newValueDict = {'Status': 'Wanted'}
        myDB.upsert("albums", newValueDict, controlValueDict)
        searcher.searchforalbum(AlbumID, new)
        if ArtistID:
            redirect = "artistPage?ArtistID=%s" % ArtistID
        raise cherrypy.HTTPRedirect(redirect)

    @cherrypy.expose
    def choose_specific_download(self, AlbumID):
        results = searcher.searchforalbum(AlbumID, choose_specific_download=True)

        results_as_dicts = []

        for result in results:
            result_dict = {
                'title': result[0],
                'size': result[1],
                'url': result[2],
                'provider': result[3],
                'kind': result[4],
                'matches': result[5]
            }
            results_as_dicts.append(result_dict)
        s = json.dumps(results_as_dicts)
        cherrypy.response.headers['Content-type'] = 'application/json'
        return s

    @cherrypy.expose
    def download_specific_release(self, AlbumID, title, size, url, provider, kind, **kwargs):
        # Handle situations where the torrent url contains arguments that are parsed
        if kwargs:
            url = urllib2.quote(url, safe=":?/=&") + '&' + urllib.urlencode(kwargs)
        try:
            result = [(title, int(size), url, provider, kind)]
        except ValueError:
            result = [(title, float(size), url, provider, kind)]

        logger.info(u"Making sure we can download the chosen result")
        (data, bestqual) = searcher.preprocess(result)

        if data and bestqual:
            myDB = db.DBConnection()
            album = myDB.action('SELECT * from albums WHERE AlbumID=?', [AlbumID]).fetchone()
            searcher.send_to_downloader(data, bestqual, album)
            return json.dumps({'result': 'success'})
        else:
            return json.dumps({'result': 'failure'})

    @cherrypy.expose
    def unqueueAlbum(self, AlbumID, ArtistID):
        logger.info(u"Marking album: " + AlbumID + "as skipped...")
        myDB = db.DBConnection()
        controlValueDict = {'AlbumID': AlbumID}
        newValueDict = {'Status': 'Skipped'}
        myDB.upsert("albums", newValueDict, controlValueDict)
        raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % ArtistID)

    @cherrypy.expose
    def deleteAlbum(self, AlbumID, ArtistID=None):
        logger.info(u"Deleting all traces of album: " + AlbumID)
        myDB = db.DBConnection()

        myDB.action('DELETE from have WHERE Matched=?', [AlbumID])
        album = myDB.action('SELECT ArtistID, ArtistName, AlbumTitle from albums where AlbumID=?',
                            [AlbumID]).fetchone()
        if album:
            ArtistID = album['ArtistID']
            myDB.action('DELETE from have WHERE ArtistName=? AND AlbumTitle=?',
                        [album['ArtistName'], album['AlbumTitle']])

        myDB.action('DELETE from albums WHERE AlbumID=?', [AlbumID])
        myDB.action('DELETE from tracks WHERE AlbumID=?', [AlbumID])
        myDB.action('DELETE from allalbums WHERE AlbumID=?', [AlbumID])
        myDB.action('DELETE from alltracks WHERE AlbumID=?', [AlbumID])
        myDB.action('DELETE from releases WHERE ReleaseGroupID=?', [AlbumID])
        myDB.action('DELETE from descriptions WHERE ReleaseGroupID=?', [AlbumID])

        from headphones import cache
        c = cache.Cache()
        c.remove_from_cache(AlbumID=AlbumID)

        if ArtistID:
            raise cherrypy.HTTPRedirect("artistPage?ArtistID=%s" % ArtistID)
        else:
            raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def switchAlbum(self, AlbumID, ReleaseID):
        """
        Take the values from allalbums/alltracks (based on the ReleaseID) and
        swap it into the album & track tables
        """
        from headphones import albumswitcher
        albumswitcher.switch(AlbumID, ReleaseID)
        raise cherrypy.HTTPRedirect("albumPage?AlbumID=%s" % AlbumID)

    @cherrypy.expose
    def editSearchTerm(self, AlbumID, SearchTerm):
        logger.info(u"Updating search term for albumid: " + AlbumID)
        myDB = db.DBConnection()
        controlValueDict = {'AlbumID': AlbumID}
        newValueDict = {'SearchTerm': SearchTerm}
        myDB.upsert("albums", newValueDict, controlValueDict)
        raise cherrypy.HTTPRedirect("albumPage?AlbumID=%s" % AlbumID)

    @cherrypy.expose
    def upcoming(self):
        myDB = db.DBConnection()
        upcoming = myDB.select(
            "SELECT * from albums WHERE ReleaseDate > date('now') order by ReleaseDate ASC")
        wanted = myDB.select("SELECT * from albums WHERE Status='Wanted'")
        return serve_template(templatename="upcoming.html", title="Upcoming", upcoming=upcoming,
                              wanted=wanted)

    @cherrypy.expose
    def manage(self):
        myDB = db.DBConnection()
        emptyArtists = myDB.select("SELECT * FROM artists WHERE LatestAlbum IS NULL")

        # DONE : softchroot
        model = {
            'MUSIC_DIR': headphones.SOFT_CHROOT.apply(headphones.CONFIG.MUSIC_DIR)
        }
        return serve_template(templatename="manage.html", title="Manage", emptyArtists=emptyArtists, model=model)

    @cherrypy.expose
    def manageArtists(self):
        myDB = db.DBConnection()
        artists = myDB.select('SELECT * from artists order by ArtistSortName COLLATE NOCASE')
        return serve_template(templatename="manageartists.html", title="Manage Artists",
                              artists=artists)

    @cherrypy.expose
    def manageAlbums(self, Status=None):
        myDB = db.DBConnection()
        if Status == "Upcoming":
            albums = myDB.select("SELECT * from albums WHERE ReleaseDate > date('now')")
        elif Status:
            albums = myDB.select('SELECT * from albums WHERE Status=?', [Status])
        else:
            albums = myDB.select('SELECT * from albums')
        return serve_template(templatename="managealbums.html", title="Manage Albums",
                              albums=albums)

    @cherrypy.expose
    def manageNew(self):
        myDB = db.DBConnection()
        newartists = myDB.select('SELECT * from newartists')
        return serve_template(templatename="managenew.html", title="Manage New Artists",
                              newartists=newartists)

    @cherrypy.expose
    def manageUnmatched(self):
        myDB = db.DBConnection()
        have_album_dictionary = []
        headphones_album_dictionary = []
        have_albums = myDB.select(
            'SELECT ArtistName, AlbumTitle, TrackTitle, CleanName from have WHERE Matched = "Failed" GROUP BY AlbumTitle ORDER BY ArtistName')
        for albums in have_albums:
            # Have to skip over manually matched tracks
            if albums['ArtistName'] and albums['AlbumTitle'] and albums['TrackTitle']:
                original_clean = helpers.clean_name(
                    albums['ArtistName'] + " " + albums['AlbumTitle'] + " " + albums['TrackTitle'])
                # else:
                #     original_clean = None
                if original_clean == albums['CleanName']:
                    have_dict = {'ArtistName': albums['ArtistName'],
                                 'AlbumTitle': albums['AlbumTitle']}
                    have_album_dictionary.append(have_dict)
        headphones_albums = myDB.select(
            'SELECT ArtistName, AlbumTitle from albums ORDER BY ArtistName')
        for albums in headphones_albums:
            if albums['ArtistName'] and albums['AlbumTitle']:
                headphones_dict = {'ArtistName': albums['ArtistName'],
                                   'AlbumTitle': albums['AlbumTitle']}
                headphones_album_dictionary.append(headphones_dict)
        # unmatchedalbums = [f for f in have_album_dictionary if f not in [x for x in headphones_album_dictionary]]

        check = set(
            [(clean_name(d['ArtistName']).lower(),
              clean_name(d['AlbumTitle']).lower()) for d in
             headphones_album_dictionary])
        unmatchedalbums = [d for d in have_album_dictionary if (
            clean_name(d['ArtistName']).lower(),
            clean_name(d['AlbumTitle']).lower()) not in check]

        return serve_template(templatename="manageunmatched.html", title="Manage Unmatched Items",
                              unmatchedalbums=unmatchedalbums)

    @cherrypy.expose
    def markUnmatched(self, action=None, existing_artist=None, existing_album=None, new_artist=None,
                      new_album=None):
        myDB = db.DBConnection()

        if action == "ignoreArtist":
            artist = existing_artist
            myDB.action(
                'UPDATE have SET Matched="Ignored" WHERE ArtistName=? AND Matched = "Failed"',
                [artist])

        elif action == "ignoreAlbum":
            artist = existing_artist
            album = existing_album
            myDB.action(
                'UPDATE have SET Matched="Ignored" WHERE ArtistName=? AND AlbumTitle=? AND Matched = "Failed"',
                (artist, album))

        elif action == "matchArtist":
            existing_artist_clean = helpers.clean_name(existing_artist).lower()
            new_artist_clean = helpers.clean_name(new_artist).lower()
            if new_artist_clean != existing_artist_clean:
                have_tracks = myDB.action(
                    'SELECT Matched, CleanName, Location, BitRate, Format FROM have WHERE ArtistName=?',
                    [existing_artist])
                update_count = 0
                for entry in have_tracks:
                    old_clean_filename = entry['CleanName']
                    if old_clean_filename.startswith(existing_artist_clean):
                        new_clean_filename = old_clean_filename.replace(existing_artist_clean,
                                                                        new_artist_clean, 1)
                        myDB.action(
                            'UPDATE have SET CleanName=? WHERE ArtistName=? AND CleanName=?',
                            [new_clean_filename, existing_artist, old_clean_filename])
                        controlValueDict = {"CleanName": new_clean_filename}
                        newValueDict = {"Location": entry['Location'],
                                        "BitRate": entry['BitRate'],
                                        "Format": entry['Format']
                                        }
                        # Attempt to match tracks with new CleanName
                        match_alltracks = myDB.action(
                            'SELECT CleanName from alltracks WHERE CleanName=?',
                            [new_clean_filename]).fetchone()
                        if match_alltracks:
                            myDB.upsert("alltracks", newValueDict, controlValueDict)
                        match_tracks = myDB.action(
                            'SELECT CleanName, AlbumID from tracks WHERE CleanName=?',
                            [new_clean_filename]).fetchone()
                        if match_tracks:
                            myDB.upsert("tracks", newValueDict, controlValueDict)
                            myDB.action('UPDATE have SET Matched="Manual" WHERE CleanName=?',
                                        [new_clean_filename])
                            update_count += 1
                            # This was throwing errors and I don't know why, but it seems to be working fine.
                            # else:
                            # logger.info("There was an error modifying Artist %s. This should not have happened" % existing_artist)
                logger.info("Manual matching yielded %s new matches for Artist: %s" % (
                update_count, new_artist))
                if update_count > 0:
                    librarysync.update_album_status()
            else:
                logger.info(
                    "Artist %s already named appropriately; nothing to modify" % existing_artist)

        elif action == "matchAlbum":
            existing_artist_clean = helpers.clean_name(existing_artist).lower()
            new_artist_clean = helpers.clean_name(new_artist).lower()
            existing_album_clean = helpers.clean_name(existing_album).lower()
            new_album_clean = helpers.clean_name(new_album).lower()
            existing_clean_string = existing_artist_clean + " " + existing_album_clean
            new_clean_string = new_artist_clean + " " + new_album_clean
            if existing_clean_string != new_clean_string:
                have_tracks = myDB.action(
                    'SELECT Matched, CleanName, Location, BitRate, Format FROM have WHERE ArtistName=? AND AlbumTitle=?',
                    (existing_artist, existing_album))
                update_count = 0
                for entry in have_tracks:
                    old_clean_filename = entry['CleanName']
                    if old_clean_filename.startswith(existing_clean_string):
                        new_clean_filename = old_clean_filename.replace(existing_clean_string,
                                                                        new_clean_string, 1)
                        myDB.action(
                            'UPDATE have SET CleanName=? WHERE ArtistName=? AND AlbumTitle=? AND CleanName=?',
                            [new_clean_filename, existing_artist, existing_album,
                             old_clean_filename])
                        controlValueDict = {"CleanName": new_clean_filename}
                        newValueDict = {"Location": entry['Location'],
                                        "BitRate": entry['BitRate'],
                                        "Format": entry['Format']
                                        }
                        # Attempt to match tracks with new CleanName
                        match_alltracks = myDB.action(
                            'SELECT CleanName from alltracks WHERE CleanName=?',
                            [new_clean_filename]).fetchone()
                        if match_alltracks:
                            myDB.upsert("alltracks", newValueDict, controlValueDict)
                        match_tracks = myDB.action(
                            'SELECT CleanName, AlbumID from tracks WHERE CleanName=?',
                            [new_clean_filename]).fetchone()
                        if match_tracks:
                            myDB.upsert("tracks", newValueDict, controlValueDict)
                            myDB.action('UPDATE have SET Matched="Manual" WHERE CleanName=?',
                                        [new_clean_filename])
                            album_id = match_tracks['AlbumID']
                            update_count += 1
                            # This was throwing errors and I don't know why, but it seems to be working fine.
                            # else:
                            # logger.info("There was an error modifying Artist %s / Album %s with clean name %s" % (existing_artist, existing_album, existing_clean_string))
                logger.info("Manual matching yielded %s new matches for Artist: %s / Album: %s" % (
                update_count, new_artist, new_album))
                if update_count > 0:
                    librarysync.update_album_status(album_id)
            else:
                logger.info(
                    "Artist %s / Album %s already named appropriately; nothing to modify" % (
                    existing_artist, existing_album))

    @cherrypy.expose
    def manageManual(self):
        myDB = db.DBConnection()
        manual_albums = []
        manualalbums = myDB.select(
            'SELECT ArtistName, AlbumTitle, TrackTitle, CleanName, Matched from have')
        for albums in manualalbums:
            if albums['ArtistName'] and albums['AlbumTitle'] and albums['TrackTitle']:
                original_clean = helpers.clean_name(
                    albums['ArtistName'] + " " + albums['AlbumTitle'] + " " + albums['TrackTitle'])
                if albums['Matched'] == "Ignored" or albums['Matched'] == "Manual" or albums[
                    'CleanName'] != original_clean:
                    if albums['Matched'] == "Ignored":
                        album_status = "Ignored"
                    elif albums['Matched'] == "Manual" or albums['CleanName'] != original_clean:
                        album_status = "Matched"
                    manual_dict = {'ArtistName': albums['ArtistName'],
                                   'AlbumTitle': albums['AlbumTitle'], 'AlbumStatus': album_status}
                    if manual_dict not in manual_albums:
                        manual_albums.append(manual_dict)
        manual_albums_sorted = sorted(manual_albums, key=itemgetter('ArtistName', 'AlbumTitle'))

        return serve_template(templatename="managemanual.html", title="Manage Manual Items",
                              manualalbums=manual_albums_sorted)

    @cherrypy.expose
    def markManual(self, action=None, existing_artist=None, existing_album=None):
        myDB = db.DBConnection()
        if action == "unignoreArtist":
            artist = existing_artist
            myDB.action('UPDATE have SET Matched="Failed" WHERE ArtistName=? AND Matched="Ignored"',
                        [artist])
            logger.info("Artist: %s successfully restored to unmatched list" % artist)

        elif action == "unignoreAlbum":
            artist = existing_artist
            album = existing_album
            myDB.action(
                'UPDATE have SET Matched="Failed" WHERE ArtistName=? AND AlbumTitle=? AND Matched="Ignored"',
                (artist, album))
            logger.info("Album: %s successfully restored to unmatched list" % album)

        elif action == "unmatchArtist":
            artist = existing_artist
            update_clean = myDB.select(
                'SELECT ArtistName, AlbumTitle, TrackTitle, CleanName, Matched from have WHERE ArtistName=?',
                [artist])
            update_count = 0
            for tracks in update_clean:
                original_clean = helpers.clean_name(
                    tracks['ArtistName'] + " " + tracks['AlbumTitle'] + " " + tracks[
                        'TrackTitle']).lower()
                album = tracks['AlbumTitle']
                track_title = tracks['TrackTitle']
                if tracks['CleanName'] != original_clean:
                    myDB.action(
                        'UPDATE tracks SET Location=?, BitRate=?, Format=? WHERE CleanName=?',
                        [None, None, None, tracks['CleanName']])
                    myDB.action(
                        'UPDATE alltracks SET Location=?, BitRate=?, Format=? WHERE CleanName=?',
                        [None, None, None, tracks['CleanName']])
                    myDB.action(
                        'UPDATE have SET CleanName=?, Matched="Failed" WHERE ArtistName=? AND AlbumTitle=? AND TrackTitle=?',
                        (original_clean, artist, album, track_title))
                    update_count += 1
            if update_count > 0:
                librarysync.update_album_status()
            logger.info("Artist: %s successfully restored to unmatched list" % artist)

        elif action == "unmatchAlbum":
            artist = existing_artist
            album = existing_album
            update_clean = myDB.select(
                'SELECT ArtistName, AlbumTitle, TrackTitle, CleanName, Matched from have WHERE ArtistName=? AND AlbumTitle=?',
                (artist, album))
            update_count = 0
            for tracks in update_clean:
                original_clean = helpers.clean_name(
                    tracks['ArtistName'] + " " + tracks['AlbumTitle'] + " " + tracks[
                        'TrackTitle']).lower()
                track_title = tracks['TrackTitle']
                if tracks['CleanName'] != original_clean:
                    album_id_check = myDB.action('SELECT AlbumID from tracks WHERE CleanName=?',
                                                 [tracks['CleanName']]).fetchone()
                    if album_id_check:
                        album_id = album_id_check[0]
                    myDB.action(
                        'UPDATE tracks SET Location=?, BitRate=?, Format=? WHERE CleanName=?',
                        [None, None, None, tracks['CleanName']])
                    myDB.action(
                        'UPDATE alltracks SET Location=?, BitRate=?, Format=? WHERE CleanName=?',
                        [None, None, None, tracks['CleanName']])
                    myDB.action(
                        'UPDATE have SET CleanName=?, Matched="Failed" WHERE ArtistName=? AND AlbumTitle=? AND TrackTitle=?',
                        (original_clean, artist, album, track_title))
                    update_count += 1
            if update_count > 0:
                librarysync.update_album_status(album_id)
            logger.info("Album: %s successfully restored to unmatched list" % album)

    @cherrypy.expose
    def markArtists(self, action=None, **args):
        myDB = db.DBConnection()
        artistsToAdd = []
        for ArtistID in args:
            if action == 'delete':
                self.removeArtist(ArtistID)
            elif action == 'pause':
                controlValueDict = {'ArtistID': ArtistID}
                newValueDict = {'Status': 'Paused'}
                myDB.upsert("artists", newValueDict, controlValueDict)
            elif action == 'resume':
                controlValueDict = {'ArtistID': ArtistID}
                newValueDict = {'Status': 'Active'}
                myDB.upsert("artists", newValueDict, controlValueDict)
            else:
                artistsToAdd.append(ArtistID)
        if len(artistsToAdd) > 0:
            logger.debug("Refreshing artists: %s" % artistsToAdd)
            threading.Thread(target=importer.addArtistIDListToDB, args=[artistsToAdd]).start()
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def importLastFM(self, username):
        headphones.CONFIG.LASTFM_USERNAME = username
        headphones.CONFIG.write()
        threading.Thread(target=lastfm.getArtists).start()
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def importLastFMTag(self, tag, limit):
        threading.Thread(target=lastfm.getTagTopArtists, args=(tag, limit)).start()
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def importItunes(self, path):
        headphones.CONFIG.PATH_TO_XML = path
        headphones.CONFIG.write()
        thread = threading.Thread(target=importer.itunesImport, args=[path])
        thread.start()
        thread.join(10)
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def musicScan(self, path, scan=0, redirect=None, autoadd=0, libraryscan=0):
        # DONE : softchroot
        headphones.CONFIG.LIBRARYSCAN = libraryscan
        headphones.CONFIG.AUTO_ADD_ARTISTS = autoadd
        headphones.CONFIG.MUSIC_DIR = headphones.SOFT_CHROOT.revoke(path)
        headphones.CONFIG.write()
        if scan:
            try:
                threading.Thread(target=librarysync.libraryScan).start()
            except Exception as e:
                logger.error('Unable to complete the scan: %s' % e)
        if redirect:
            raise cherrypy.HTTPRedirect(redirect)
        else:
            raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def forceUpdate(self):
        from headphones import updater
        threading.Thread(target=updater.dbUpdate, args=[False]).start()
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def forceFullUpdate(self):
        from headphones import updater
        threading.Thread(target=updater.dbUpdate, args=[True]).start()
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def forceSearch(self):
        from headphones import searcher
        threading.Thread(target=searcher.searchforalbum).start()
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def forcePostProcess(self, dir=None, album_dir=None, keep_original_folder=False):
        # DONE : softchroot
        from headphones import postprocessor
        threading.Thread(target=postprocessor.forcePostProcess,
                         kwargs={
                             'dir': headphones.SOFT_CHROOT.revoke(dir),
                             'album_dir': headphones.SOFT_CHROOT.revoke(album_dir),
                             'keep_original_folder': keep_original_folder == 'True'
                         }).start()
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def checkGithub(self):
        from headphones import versioncheck
        versioncheck.checkGithub()
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def history(self):
        myDB = db.DBConnection()
        history = myDB.select(
            '''SELECT AlbumID, Title, Size, URL, DateAdded, Status, Kind, ifnull(FolderName, '?') FolderName FROM snatched WHERE Status NOT LIKE "Seed%" ORDER BY DateAdded DESC''')
        return serve_template(templatename="history.html", title="History", history=history)

    @cherrypy.expose
    def logs(self):
        return serve_template(templatename="logs.html", title="Log", lineList=headphones.LOG_LIST)

    @cherrypy.expose
    def clearLogs(self):
        headphones.LOG_LIST = []
        logger.info("Web logs cleared")
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    def toggleVerbose(self):
        headphones.VERBOSE = not headphones.VERBOSE
        logger.initLogger(console=not headphones.QUIET,
                          log_dir=headphones.CONFIG.LOG_DIR, verbose=headphones.VERBOSE)
        logger.info("Verbose toggled, set to %s", headphones.VERBOSE)
        logger.debug("If you read this message, debug logging is available")
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    def getLog(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc",
               sSearch="", **kwargs):
        iDisplayStart = int(iDisplayStart)
        iDisplayLength = int(iDisplayLength)

        filtered = []
        if sSearch == "":
            filtered = headphones.LOG_LIST[::]
        else:
            filtered = [row for row in headphones.LOG_LIST for column in row if
                        sSearch.lower() in column.lower()]

        sortcolumn = 0
        if iSortCol_0 == '1':
            sortcolumn = 2
        elif iSortCol_0 == '2':
            sortcolumn = 1
        filtered.sort(key=lambda x: x[sortcolumn], reverse=sSortDir_0 == "desc")

        rows = filtered[iDisplayStart:(iDisplayStart + iDisplayLength)]
        rows = [[row[0], row[2], row[1]] for row in rows]

        return json.dumps({
            'iTotalDisplayRecords': len(filtered),
            'iTotalRecords': len(headphones.LOG_LIST),
            'aaData': rows,
        })

    @cherrypy.expose
    def getArtists_json(self, iDisplayStart=0, iDisplayLength=100, sSearch="", iSortCol_0='0',
                        sSortDir_0='asc', **kwargs):
        iDisplayStart = int(iDisplayStart)
        iDisplayLength = int(iDisplayLength)
        filtered = []
        totalcount = 0
        myDB = db.DBConnection()

        sortcolumn = 'ArtistSortName'
        sortbyhavepercent = False
        if iSortCol_0 == '2':
            sortcolumn = 'Status'
        elif iSortCol_0 == '3':
            sortcolumn = 'ReleaseDate'
        elif iSortCol_0 == '4':
            sortbyhavepercent = True

        if sSearch == "":
            query = 'SELECT * from artists order by %s COLLATE NOCASE %s' % (sortcolumn, sSortDir_0)
            filtered = myDB.select(query)
            totalcount = len(filtered)
        else:
            query = 'SELECT * from artists WHERE ArtistSortName LIKE "%' + sSearch + '%" OR LatestAlbum LIKE "%' + sSearch + '%"' + 'ORDER BY %s COLLATE NOCASE %s' % (
            sortcolumn, sSortDir_0)
            filtered = myDB.select(query)
            totalcount = myDB.select('SELECT COUNT(*) from artists')[0][0]

        if sortbyhavepercent:
            filtered.sort(key=lambda x: (
            float(x['HaveTracks']) / x['TotalTracks'] if x['TotalTracks'] > 0 else 0.0,
            x['HaveTracks'] if x['HaveTracks'] else 0.0), reverse=sSortDir_0 == "asc")

        # can't figure out how to change the datatables default sorting order when its using an ajax datasource so ill
        # just reverse it here and the first click on the "Latest Album" header will sort by descending release date
        if sortcolumn == 'ReleaseDate':
            filtered.reverse()

        artists = filtered[iDisplayStart:(iDisplayStart + iDisplayLength)]
        rows = []
        for artist in artists:
            row = {"ArtistID": artist['ArtistID'],
                   "ArtistName": artist["ArtistName"],
                   "ArtistSortName": artist["ArtistSortName"],
                   "Status": artist["Status"],
                   "TotalTracks": artist["TotalTracks"],
                   "HaveTracks": artist["HaveTracks"],
                   "LatestAlbum": "",
                   "ReleaseDate": "",
                   "ReleaseInFuture": "False",
                   "AlbumID": "",
                   }

            if not row['HaveTracks']:
                row['HaveTracks'] = 0
            if artist['ReleaseDate'] and artist['LatestAlbum']:
                row['ReleaseDate'] = artist['ReleaseDate']
                row['LatestAlbum'] = artist['LatestAlbum']
                row['AlbumID'] = artist['AlbumID']
                if artist['ReleaseDate'] > today():
                    row['ReleaseInFuture'] = "True"
            elif artist['LatestAlbum']:
                row['ReleaseDate'] = ''
                row['LatestAlbum'] = artist['LatestAlbum']
                row['AlbumID'] = artist['AlbumID']

            rows.append(row)

        dict = {'iTotalDisplayRecords': len(filtered),
                'iTotalRecords': totalcount,
                'aaData': rows,
                }
        s = json.dumps(dict)
        cherrypy.response.headers['Content-type'] = 'application/json'
        return s

    @cherrypy.expose
    def getAlbumsByArtist_json(self, artist=None):
        myDB = db.DBConnection()
        album_json = {}
        counter = 0
        album_list = myDB.select("SELECT AlbumTitle from albums WHERE ArtistName=?", [artist])
        for album in album_list:
            album_json[counter] = album['AlbumTitle']
            counter += 1
        json_albums = json.dumps(album_json)

        cherrypy.response.headers['Content-type'] = 'application/json'
        return json_albums

    @cherrypy.expose
    def getArtistjson(self, ArtistID, **kwargs):
        myDB = db.DBConnection()
        artist = myDB.action('SELECT * FROM artists WHERE ArtistID=?', [ArtistID]).fetchone()
        artist_json = json.dumps({
            'ArtistName': artist['ArtistName'],
            'Status': artist['Status']
        })
        return artist_json

    @cherrypy.expose
    def getAlbumjson(self, AlbumID, **kwargs):
        myDB = db.DBConnection()
        album = myDB.action('SELECT * from albums WHERE AlbumID=?', [AlbumID]).fetchone()
        album_json = json.dumps({
            'AlbumTitle': album['AlbumTitle'],
            'ArtistName': album['ArtistName'],
            'Status': album['Status']
        })
        return album_json

    @cherrypy.expose
    def clearhistory(self, type=None, date_added=None, title=None):
        myDB = db.DBConnection()
        if type:
            if type == 'all':
                logger.info(u"Clearing all history")
                myDB.action('DELETE from snatched WHERE Status NOT LIKE "Seed%"')
            else:
                logger.info(u"Clearing history where status is %s" % type)
                myDB.action('DELETE from snatched WHERE Status=?', [type])
        else:
            logger.info(u"Deleting '%s' from history" % title)
            myDB.action(
                'DELETE from snatched WHERE Status NOT LIKE "Seed%" AND Title=? AND DateAdded=?',
                [title, date_added])
        raise cherrypy.HTTPRedirect("history")

    @cherrypy.expose
    def generateAPI(self):
        apikey = hashlib.sha224(str(random.getrandbits(256))).hexdigest()[0:32]
        logger.info("New API generated")
        return apikey

    @cherrypy.expose
    def forceScan(self, keepmatched=None):
        myDB = db.DBConnection()
        #########################################
        # NEED TO MOVE THIS INTO A SEPARATE FUNCTION BEFORE RELEASE
        myDB.select('DELETE from Have')
        logger.info('Removed all entries in local library database')
        myDB.select('UPDATE alltracks SET Location=NULL, BitRate=NULL, Format=NULL')
        myDB.select('UPDATE tracks SET Location=NULL, BitRate=NULL, Format=NULL')
        logger.info('All tracks in library unmatched')
        myDB.action('UPDATE artists SET HaveTracks=NULL')
        logger.info('Reset track counts for all artists')
        myDB.action(
            'UPDATE albums SET Status="Skipped" WHERE Status="Skipped" OR Status="Downloaded"')
        logger.info('Marking all unwanted albums as Skipped')
        try:
            threading.Thread(target=librarysync.libraryScan).start()
        except Exception as e:
            logger.error('Unable to complete the scan: %s' % e)
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def configMetaUi(self):
        # TODO : load config
        #      : it is handler for configuring meta-ui through UI
        config = None
        return serve_template(templatename="config-meta-ui.html", title="Meta UI Settings", config=config)

    @cherrypy.expose
    def configMetaUiUpdate(self, **kwargs):
        # TODO : save config
        #      : it is handler for saving meta-ui received from UI
        print('configMetaUiUpdate', kwargs)
        raise cherrypy.HTTPRedirect("configMetaUi")

    @cherrypy.expose
    def config(self):
        logger.debug("config requested")

        model = headphones.CONFIG.getViewModel()
        response = serve_template(templatename="config.html", title=_("Settings"), model=model)

        logger.debug("config request handled")
        return response

    @cherrypy.expose
    def configUpdate(self, **kwargs):
        try:
            headphones.CONFIG.accept(kwargs)
        except Exception as exc:
            logger.error("{0}: {1}".format(type(exc), exc))
            raise

        # TODO : implement VALIDATION in options!!
        # Sanity checking
        if headphones.CONFIG.SEARCH_INTERVAL and headphones.CONFIG.SEARCH_INTERVAL < 360:
            logger.info("Search interval too low. Resetting to 6 hour minimum")
            headphones.CONFIG.SEARCH_INTERVAL = 360

        # write config to the file
        try:
            headphones.CONFIG.write()
        except Exception as exc:
            logger.error("{0}: {1}".format(type(exc), exc))
            raise

        # Reconfigure scheduler
        headphones.initialize_scheduler()

        # Reconfigure musicbrainz database connection with the new values
        mb.startmb()

        raise cherrypy.HTTPRedirect("config")

    @cherrypy.expose
    def do_state_change(self, signal, title, timer):
        headphones.SIGNAL = signal
        message = title + '...'
        return serve_template(templatename="shutdown.html", title=title,
                              message=message, timer=timer)

    @cherrypy.expose
    def shutdown(self):
        return self.do_state_change('shutdown', 'Shutting Down', 15)

    @cherrypy.expose
    def restart(self):
        return self.do_state_change('restart', 'Restarting', 30)

    @cherrypy.expose
    def update(self):
        return self.do_state_change('update', 'Updating', 120)

    @cherrypy.expose
    def extras(self):
        myDB = db.DBConnection()
        cloudlist = myDB.select('SELECT * from lastfmcloud')
        return serve_template(templatename="extras.html", title="Extras", cloudlist=cloudlist)

    @cherrypy.expose
    def addReleaseById(self, rid, rgid=None):
        threading.Thread(target=importer.addReleaseById, args=[rid, rgid]).start()
        if rgid:
            raise cherrypy.HTTPRedirect("albumPage?AlbumID=%s" % rgid)
        else:
            raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    def updateCloud(self):
        lastfm.getSimilar()
        raise cherrypy.HTTPRedirect("extras")

    @cherrypy.expose
    def api(self, *args, **kwargs):
        from headphones.api import Api

        a = Api()
        a.checkParams(*args, **kwargs)

        return a.fetchData()

    @cherrypy.expose
    def getInfo(self, ArtistID=None, AlbumID=None):

        from headphones import cache
        info_dict = cache.getInfo(ArtistID, AlbumID)

        return json.dumps(info_dict)

    @cherrypy.expose
    def getArtwork(self, ArtistID=None, AlbumID=None):

        from headphones import cache
        return cache.getArtwork(ArtistID, AlbumID)

    @cherrypy.expose
    def getThumb(self, ArtistID=None, AlbumID=None):

        from headphones import cache
        return cache.getThumb(ArtistID, AlbumID)

    # If you just want to get the last.fm image links for an album, make sure
    # to pass a releaseid and not a releasegroupid
    @cherrypy.expose
    def getImageLinks(self, ArtistID=None, AlbumID=None):
        from headphones import cache
        image_dict = cache.getImageLinks(ArtistID, AlbumID)

        # Return the Cover Art Archive urls if not found on last.fm
        if AlbumID and not image_dict:
            image_url = "http://coverartarchive.org/release/%s/front-500.jpg" % AlbumID
            thumb_url = "http://coverartarchive.org/release/%s/front-250.jpg" % AlbumID
            image_dict = {'artwork': image_url, 'thumbnail': thumb_url}
        elif AlbumID and (not image_dict['artwork'] or not image_dict['thumbnail']):
            if not image_dict['artwork']:
                image_dict[
                    'artwork'] = "http://coverartarchive.org/release/%s/front-500.jpg" % AlbumID
            if not image_dict['thumbnail']:
                image_dict[
                    'thumbnail'] = "http://coverartarchive.org/release/%s/front-250.jpg" % AlbumID

        return json.dumps(image_dict)

    @cherrypy.expose
    def twitterStep1(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        tweet = notifiers.TwitterNotifier()
        return tweet._get_authorization()

    @cherrypy.expose
    def twitterStep2(self, key):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        tweet = notifiers.TwitterNotifier()
        result = tweet._get_credentials(key)
        logger.info(u"result: " + str(result))
        if result:
            return "Key verification successful"
        else:
            return "Unable to verify key"

    @cherrypy.expose
    def testTwitter(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        tweet = notifiers.TwitterNotifier()
        result = tweet.test_notify()
        if result:
            return "Tweet successful, check your twitter to make sure it worked"
        else:
            return "Error sending tweet"

    @cherrypy.expose
    def osxnotifyregister(self, app):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        from osxnotify import registerapp as osxnotify
        result, msg = osxnotify.registerapp(app)
        if result:
            osx_notify = notifiers.OSX_NOTIFY()
            osx_notify.notify('Registered', result, 'Success :-)')
            logger.info(
                'Registered %s, to re-register a different app, delete this app first' % result)
        else:
            logger.warn(msg)
        return msg

    @cherrypy.expose
    def testPushover(self):
        logger.info(u"Sending Pushover notification")
        pushover = notifiers.PUSHOVER()
        result = pushover.notify("hooray!", "This is a test")
        return str(result)

    @cherrypy.expose
    def testPlex(self):
        logger.info(u"Testing plex notifications")
        plex = notifiers.Plex()
        plex.notify("hellooooo", "test album!", "")

    @cherrypy.expose
    def testPushbullet(self):
        logger.info("Testing Pushbullet notifications")
        pushbullet = notifiers.PUSHBULLET()
        pushbullet.notify("it works!", "Test message")

    @cherrypy.expose
    def testTelegram(self):
        logger.info("Testing Telegram notifications")
        telegram = notifiers.TELEGRAM()
        telegram.notify("it works!", "lazers pew pew")


class Artwork(object):

    @cherrypy.expose
    def index(self):
        return "Artwork"

    @cherrypy.expose
    def default(self, ArtistOrAlbum="", ID=None):
        from headphones import cache
        ArtistID = None
        AlbumID = None
        if ArtistOrAlbum == "artist":
            ArtistID = ID
        elif ArtistOrAlbum == "album":
            AlbumID = ID

        relpath = cache.getArtwork(ArtistID, AlbumID)

        if not relpath:
            relpath = "data/interfaces/default/images/no-cover-art.png"
            basedir = os.path.dirname(sys.argv[0])
            path = os.path.join(basedir, relpath)
            cherrypy.response.headers['Content-type'] = 'image/png'
            cherrypy.response.headers['Cache-Control'] = 'no-cache'
        else:
            relpath = relpath.replace('cache/', '', 1)
            path = os.path.join(headphones.CONFIG.CACHE_DIR, relpath)
            fileext = os.path.splitext(relpath)[1][1::]
            cherrypy.response.headers['Content-type'] = 'image/' + fileext
            cherrypy.response.headers['Cache-Control'] = 'max-age=31556926'

        with open(os.path.normpath(path), "rb") as fp:
            return fp.read()

    class Thumbs(object):

        @cherrypy.expose
        def index(self):
            return "Here be thumbs"

        @cherrypy.expose
        def default(self, ArtistOrAlbum="", ID=None):
            from headphones import cache
            ArtistID = None
            AlbumID = None
            if ArtistOrAlbum == "artist":
                ArtistID = ID
            elif ArtistOrAlbum == "album":
                AlbumID = ID

            relpath = cache.getThumb(ArtistID, AlbumID)

            if not relpath:
                relpath = "data/interfaces/default/images/no-cover-artist.png"
                basedir = os.path.dirname(sys.argv[0])
                path = os.path.join(basedir, relpath)
                cherrypy.response.headers['Content-type'] = 'image/png'
                cherrypy.response.headers['Cache-Control'] = 'no-cache'
            else:
                relpath = relpath.replace('cache/', '', 1)
                path = os.path.join(headphones.CONFIG.CACHE_DIR, relpath)
                fileext = os.path.splitext(relpath)[1][1::]
                cherrypy.response.headers['Content-type'] = 'image/' + fileext
                cherrypy.response.headers['Cache-Control'] = 'max-age=31556926'

            with open(os.path.normpath(path), "rb") as fp:
                return fp.read()

    thumbs = Thumbs()


WebInterface.artwork = Artwork()
