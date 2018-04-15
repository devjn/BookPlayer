#!/usr/bin/env python
# encoding: utf-8

"""
player.py

The audio player. A simple wrapper around the MPD client. Uses a lockable version
of the MPD client object, because we're using multiple threads
"""


__version_info__ = (0, 0, 1)
__version__ = '.'.join(map(str, __version_info__))
__author__ = "Willem van der Jagt"


from mpd import MPDClient
from threading import Lock
from threading import RLock
from book import Book
from subprocess import call
import config
import re
import os


class LockableMPDClient(MPDClient):
    def __init__(self, use_unicode=False):
        super(LockableMPDClient, self).__init__()
        self.use_unicode = use_unicode
        self._lock = Lock()
    def acquire(self):
        self._lock.acquire()
    def release(self):
        self._lock.release()
    def __enter__(self):
        self.acquire()
    def __exit__(self, type, value, traceback):
        self.release() 


class Player(object):

    """The class responsible for playing the audio books"""

    def __init__(self, conn_details, status_light):
        
        """Setup a connection to MPD to be able to play audio.
        Also update the MPD database with any new MP3 files that may have been added
        and clear any existing playlists.
        """
        self.status_light = status_light
        self.book = Book()
        self.book_titles = []
        
        self.index_lock = RLock()
        self.current_index = -1;

        self.mpd_client = LockableMPDClient()
        with self.mpd_client:
            self.mpd_client.connect(**conn_details)

            self.mpd_client.update()
            self.mpd_client.clear()
            self.mpd_client.setvol(100)
            
            files = self.mpd_client.search('filename', ".mp3")
            if not files:
                self.status_light.interrupt('blink_fast', 3)
            else:
                for file in files:
                    book_title = os.path.dirname(file['file']) + "/"
                    if book_title not in self.book_titles:
                        self.book_titles.append(book_title) 


    def toggle_pause(self, channel):
        """Toggle playback status between play and pause"""
        
        with self.mpd_client:
            state = self.mpd_client.status()['state']
            if state == 'play':
                self.status_light.action = 'blink_pauze'
                self.mpd_client.pause()
            elif state == 'pause':
                self.status_light.action = 'blink'
                self.mpd_client.play()
            else:
                self.status_light.interrupt('blink_fast', 3)

    def rewind(self, channel):
        """Rewind by 30s"""
        self.status_light.interrupt('blink_fast', 3)
        if self.is_playing():
            song_index = int(self.book.part) - 1
            elapsed = int(self.book.elapsed)

            with self.mpd_client:

                if elapsed > 30:
                    # rewind withing current file if possible
                    self.mpd_client.seek(song_index, elapsed - 30)
                elif song_index > 0:
                    # rewind to previous file if we're not yet 30 seconds into
                    # the current file
                    prev_song = self.mpd_client.playlistinfo(song_index - 1)[0]
                    prev_song_len = int(prev_song['time'])

                    # if the previous part is longer than 30 seconds, rewind to 30
                    # seconds before the end, otherwise rewind to the start of it
                    if prev_song_len > 30:
                        self.mpd_client.seek(song_index - 1, prev_song_len - 30)
                    else:
                        self.mpd_client.seek(song_index - 1, 0)
                else:
                    # if we're less than 30 seconds into the first part, rewind
                    # to the start of it
                    self.mpd_client.seek(0, 0)


    def volume_up(self, channel):
        volume = int(self.get_status()['volume'])
        self.set_volume(min(volume + 5, 100))


    def volume_down(self, channel):

        volume = int(self.get_status()['volume'])
        self.set_volume(max(volume - 5, 0))


    def set_volume(self, volume):
        """Set the volume on the MPD client"""
        self.status_light.interrupt('blink_fast', 3)
        with self.mpd_client:
            self.mpd_client.setvol(volume)


    def stop(self):
        """On stopping, reset the current playback and stop and clear the playlist
        
        In contract to pausing, stopping is actually meant to completely stop playing
        the current book and start listening to another"""

        self.playing = False
        self.book.reset()
        
        self.status_light.action = 'on'

        with self.mpd_client:
            self.mpd_client.stop()
            self.mpd_client.clear()


    def play(self, book_title, progress=None):
        
        #print "Play title: " , book_title
        
        """Play the book as defined in self.book
        
        1. Get the parts from the current book and add them to the playlsit
        2. Start playing the playlist
        3. Immediately set the position the last know position to resume playback where
           we last left off"""

        def sorter(file1, file2):

            """sorting algorithm for files in playlist"""
            pattern = '(\d+)(-(.+))?\.mp3'
            
            try:
                file1_index = re.search(pattern, file1).groups()[1] or 0
                file2_index = re.search(pattern, file2).groups()[1] or 0

                return -1 if int(file1_index) < int(file2_index) else 1
            except:
                return 0

        
        with self.mpd_client:
            
            self.set_title_index(book_title)
            
            parts = self.mpd_client.search('filename', book_title)
            
            if not parts:
                self.status_light.interrupt('blink_fast', 3)
                return
                
            self.mpd_client.clear()
            
            for part in sorted(parts, cmp=sorter):
                self.mpd_client.add(part['file'])
                
            self.book.book_title = book_title
            
            
            if progress:
                # resume at last known position
                self.book.set_progress(progress)
                self.mpd_client.seek(int(self.book.part) - 1, int(self.book.elapsed))
            else:
                # start playing from the beginning
                self.mpd_client.play()
                
            #print("Now playing: %s %s" % (self.book.book_title, self.book.part))
        
        self.status_light.action = 'blink'
        self.book.file_info = self.get_file_info()


    def get_book_titles(self):
        return self.book_titles
        
        
    def first_title(self):
        if len(self.book_titles) == 0:
            self.status_light.interrupt('blink_fast', 3)
            return ""
    
        with self.index_lock:
            self.current_index = 0;
                
            return self.book_titles[0]
        
    def next_title(self, channel): 
        with self.index_lock:
            if len(self.book_titles) <= self.current_index + 1:
                return self.first_title()
        
            self.current_index += 1
            return self.book_titles[self.current_index]
    
    def get_title(self):
        with self.index_lock:
            if self.current_index < 0 or len(self.book_titles) <= self.current_index:
                return ""
          
            return self.book_titles[self.current_index]  
        
    def set_title_index(self, book_title):
        with self.index_lock:
            idx = self.book_titles.index(book_title)
            if idx >= 0:
                self.current_index = idx
    
    def get_parts(self, book_title):
        with self.mpd_client:
            return self.mpd_client.search('filename', book_title)
        
    def is_playing(self):
        return self.get_status()['state'] == 'play'

    def finished_book(self):
        """return if a book has finished, in which case we need to delete it from the db
        or otherwise we could never listen to that particular book again"""
        
        status = self.get_status()
        return self.book.book_title != "" and \
               status['state'] == 'stop' and \
               self.book.part == int(status['playlistlength']) and \
               'time' in self.book.file_info and float(self.book.file_info['time']) - self.book.elapsed < 20



    def get_status(self):
        with self.mpd_client:
            return self.mpd_client.status()


    def get_file_info(self):
        with self.mpd_client:
            return self.mpd_client.currentsong()


    def close(self):
        self.stop()
        with self.mpd_client:
            self.mpd_client.close()
            self.mpd_client.disconnect()
