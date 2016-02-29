from __future__ import print_function
from os import listdir
from time import sleep
from random import choice
import pygame
from espeak import espeak
import re
from dateutil.parser import parse
#from collections import namedtuple
from datetime import datetime

DIRECTORY = './recordings/OTRadio/'
FILES = listdir(DIRECTORY)

def parse_date(name):
    #Finds any 6 or 8 digit date with D/M/Y unseparated
    #or separated by '-' or '/'
    date = re.search("([\d][-/]?){6}|([\d][-/]?){8}", name)
    if date:
        date = parse(date.group(0), yearfirst=True)
    else:
        # need to define a value for unpasrseable name
        pass
    return date

def parse_dates_in_library(library_directory):
    """
    Goes through a list of file names and creates a dict
    containing a datetime and the corresponding filename for
    every file with a date in the title.
    """
    datedict = {}
    filenames = open(library_directory)
  
    for name in filenames:
        date = parse_date(name)
        datedict[date] = name        
    return datedict

"""
These are the details to be tracked for each recording available to be played.
Notes:
    ID(str) is a randomly assigned identifier when an item is first identified
    Filename(str) is the usual filename.ext 
    URL(str) is a universal resource locator for the recording. this can be used for online streams
    Release_date(datetime) is the original date that this recording was made/aired
    Description(str) use as needed to describe recording
    Genre(str) News, Comedy, Drama, Commercial, etc...
    Length(int) Total playing time in seconds. For straming media this should be set to 'Nonetype' or maybe -1
    Num_of_plays(int) Starts at zero and increment for each time played
    Last_played(datetime) timestamp
    Available(bool) was this recording available the last time it was tried?
    Unavailable_list(list(datetime)) a timestamp for each unplayable attempt
    Was_interrupted(list(tuple(datetime, length(int)))) A list of events where the user skipped a recording and the number of seconds played before interruption.
"""

Identifier = 100000
Recording_dict = {}  # TODO create storage and retrieval routines

# parse dates from filenames and build dictionary
print('Building database...')
for f in FILES:
    date = parse_date(f)
    Identifier += 1
    r = {}
    # create the minimum needed entries
    r['ID'] = str(Identifier)
    r['Filename'] = f
    r['URL'] = DIRECTORY + f
    r['Release_date'] = date
    r['Description'] = None
    r['Genre'] = None
    r['Length'] = 0
    r['Num_of_plays'] = 0
    r['Last_played'] = None
    r['Available'] = None
    r['Unavailable_list'] = []
    r['Was_interrupted'] = []
    Recording_dict[r['URL']] = r
print('Finished.')

# initialize pygame audio mixer
pygame.init()
pygame.mixer.init()
pygame.mixer.music.set_volume(1)

def play(file_url):

    # we are ready to play the file
    print('Playing: ', Recording_dict[file_url]['Filename'])
    print('Parsed date from filename is: ', Recording_dict[file_url]['Release_date'])
    Recording_dict[file_url]['Last_played'] = datetime.now()

    try:
        pygame.mixer.music.load(file_url)
        pygame.mixer.music.play()
    except:
        print('Could not play file: ', Recording_dict[file_url]['Filename'])
        # record details in the dictionary
        Recording_dict[file_url]['Unavailable_list'].append(datetime.now())
    return Recording_dict[file_url]['Filename']

def speak(text, gender='f3', emphasis='5', speed='150'):
    """
    Speak the TEXT value using espeak module
    """
    espeak.synth(text)

def load_datetime():
    """
    Get the current date and time from the system.
    Check for presence of a hardware real-time-clock and compare result
    to system time. If there is a discrepancy, try to find an NTP server
    to verify actual real-world time. 
    Order of precedence is; NTP, RTC, system-clock.
    """

def filter_files(files, parameter):
    """
    Return a subset of the files defined by parameter
    """
    return files

def pick_a_random_file(files_list, play_a_commercial=False):

    def a_commercial(file_name):
        if 'Commercial' in file_name:
            print(file_name, '... Has commercial in name.')
            return True
        return False

    selected_file = choice(files_list)

    # play the correct type of file
    if play_a_commercial:
        while not a_commercial(selected_file):
            selected_file = choice(files_list)
    else:
        while a_commercial(selected_file):
            selected_file = choice(files_list)

    return DIRECTORY + selected_file

# end of function declarations


if __name__ == '__main__': #begin operation of radio
    sleep(1)
    speak('welcome to the old time radio project')
    print('System time is: ', datetime.now())
    sleep(5)
    we_should_play_a_commercial = False
    while True:
        playcount = 300
        current_file_url = pick_a_random_file(FILES, we_should_play_a_commercial)
        play(current_file_url)

        while pygame.mixer.music.get_busy() == True and playcount:
            sleep(1)
            if not playcount % 50:
                print(playcount, ' seconds left to play.')
            playcount -= 1

        we_should_play_a_commercial = not we_should_play_a_commercial
