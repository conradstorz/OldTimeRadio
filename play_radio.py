from __future__ import print_function
from os import listdir
from time import sleep
from random import choice
import pygame
from espeak import espeak

DIRECTORY = './recordings/OTRadio/'
FILES = listdir(DIRECTORY)

pygame.init()
pygame.mixer.init()
pygame.mixer.music.set_volume(1)

def play(files_list, we_should_play_a_commercial=False):

    def a_commercial(file_name):
        if 'Commercial' in file_name:
            print('Has commercial in name.')
            return True
        return False

    selected_file = choice(files_list)
    
    # play the correct type of file
    if we_should_play_a_commercial:
        while not(a_commercial(selected_file)):
            selected_file = choice(files_list)
    else:
        while a_commercial(selected_file):
            selected_file = choice(files_list)

    try:
        pygame.mixer.music.load(DIRECTORY + selected_file)
        print('Playing: ', selected_file)
        pygame.mixer.music.play()
    except:
        print('Could not play file: ', selected_file)
    return (selected_file, we_should_play_a_commercial)

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
    to verify actual real-world time. Order of precedence is; NTP, RTC, system-clock.
    """

def filter_files(files, parameter):
    """
    Return a subset of the files defined by parameter
    """
    return files

# end of function declarations


if __name__ == '__main__': #begin operation of radio
    sleep(1)
    speak('welcome to the old time radio project')
    sleep(5)
    while True:
        we_should_play_a_commercial = False
        playcount = 300
        current_file = play(FILES, we_should_play_a_commercial)
        print(current_file)
        while pygame.mixer.music.get_busy() == True and playcount:
            sleep(1)
            if not (playcount % 50):
                print(playcount, ' seconds left to play.')
            playcount -= 1
        
        if current_file[1] == False:  # is this a commercial? (True is commercial)
            should_we_play_a_commercial = True
        else:
            should_we_play_a_commercial = False
