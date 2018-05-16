#!/usr/bin/env python
# encoding: utf-8

"""
main.py

The entry point for the book reader application.
"""

__version_info__ = (0, 0, 1)
__version__ = '.'.join(map(str, __version_info__))
__author__ = "Willem van der Jagt"


import time
import sqlite3
import pdb
import signal
import sys, os
import config
import RPi.GPIO as GPIO
from player import Player
from status_light import StatusLight
from threading import Thread
import subprocess

class BookReader(object):

    """The main class that controls the player, the GPIO pins and the RFID reader"""


    def __init__(self):
        """Initialize all the things"""
        
        # setup signal handlers. SIGINT for KeyboardInterrupt
        # and SIGTERM for when running from supervisord
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.status_light = StatusLight(config.status_light_pin)
        thread = Thread(target=self.status_light.start)
        thread.start()

        self.setup_db()
        self.player = Player(config.mpd_conn, self.status_light)
        self.setup_gpio()
        
        
    def setup_db(self):
        """Setup a connection to the SQLite db"""

        self.db_conn = sqlite3.connect(config.db_file)
        self.db_cursor = self.db_conn.cursor()


    def setup_gpio(self):
        """Setup all GPIO pins"""

        GPIO.setmode(GPIO.BCM)

        # input pins for buttons
        for pin in config.gpio_pins:
            GPIO.setup(pin['pin_id'], GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(pin['pin_id'], GPIO.FALLING, callback=getattr(self.player, pin['callback']), bouncetime=pin['bounce_time'])


    def signal_handler(self, signal, frame):
        """When quiting, stop playback, close the player and release GPIO pins"""

        self.player.close()
        self.status_light.exit()
        GPIO.cleanup()
        sys.exit(0)


    def loop(self):
        """The main event loop. This is where we look for new RFID cards on the RFID reader. If one is
        present and different from the book that's currently playing, in which case:
        
        1. Stop playback of the current book if one is playing
        2. Start playing
        """
        
        """Start with saved active book
        If there is currently none, use empty string as book title.
        This causes player to start with first book in collection.
        """
        book_title = reader.get_active_book_title()
        if not book_title:
            book_title = self.player.first_title()
                   
        #print "Titles " , self.player.get_book_titles()
        #print "Active title ", book_title
        
        
        while True:
            
            if self.player.is_playing():
                self.on_playing()
            elif self.player.finished_book():
                # when at the end of a book, delete its progress from the db
                # so we can listen to it again
                self.db_cursor.execute(
                    'DELETE FROM progress WHERE book_title = "%s"' % self.player.book.book_title)
                self.db_conn.commit()
                self.player.book.reset()
                # advance to next book
                self.player.next_title()
            
            currently_playing_title = self.player.book.book_title
            
            title = self.player.get_title()
            if title and title != book_title:
                book_title = title
                                
            if book_title:
                if book_title != currently_playing_title: 
                    reader.speak(book_title);
                    title = self.player.get_title()
                    if title == book_title:
                        progress = self.db_cursor.execute(
                        'SELECT * FROM progress WHERE book_title = "%s"' % book_title).fetchone()

                        self.player.play(book_title, progress)
                        reader.save_active_book_title(book_title)
                    
            time.sleep(1)

    def save_active_book_title(self, book_title):
                
        self.db_cursor.execute('DELETE FROM currentbook')
        
        """Save currently playing book title to database"""
        self.db_cursor.execute(
            'INSERT OR REPLACE INTO currentbook (book_title) VALUES ("%s")' %\
                (book_title))

        self.db_conn.commit()
        self.player.set_title_index(book_title)
        
    def get_active_book_title(self):
                
        """Get current book title from database or empty string
        """
        current = self.db_cursor.execute(
                        'SELECT * FROM currentbook').fetchone()
                        
        if current and current in self.player.get_book_titles():
            return current[0]
        else:
            return ""
        
    def speak(self, text):
        text = text[:-1]
        text = text.replace('_', ' ')
        
        for c in ['/', ',', '!']:
            text = text.replace(c, '<break time="500ms"/>')
        

        FNULL = open(os.devnull, 'w')
        subprocess.call(["mpc", "stop"], stdout=FNULL, stderr=subprocess.STDOUT, close_fds=True)
        subprocess.call(["pico2wave", "-lde-DE", "-w/tmp/tts.wav", text])
        FNULL = open(os.devnull, 'w')
        subprocess.call(["aplay", "/tmp/tts.wav"], stdout=FNULL, stderr=subprocess.STDOUT, close_fds=True)
        
    def on_playing(self):

        """Executed for each loop execution. Here we update self.player.book with the latest known position
        and save the prigress to db"""

        status = self.player.get_status()

        self.player.book.elapsed = float(status['elapsed'])
        self.player.book.part = int(status['song']) + 1

        #print "%s second of part %s" % (self.player.book.elapsed,  self.player.book.part)

        self.db_cursor.execute(
                'INSERT OR REPLACE INTO progress (book_title, part, elapsed) VALUES ("%s", %d, %f)' %\
                (self.player.book.book_title, self.player.book.part, self.player.book.elapsed))

        self.db_conn.commit()


if __name__ == '__main__':
    reader = BookReader()
    reader.loop()
