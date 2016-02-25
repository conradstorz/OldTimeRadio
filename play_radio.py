from os import listdir
from time import sleep
from random import choice
import pygame
import espeak

DIRECTORY = './recordings/OTRadio/'
FILES = listdir(DIRECTORY)

pygame.init()
pygame.mixer.init()
pygame.mixer.music.set_volume(1)

def play(files_list):
    current_file = choice(files_list)
    try:
        pygame.mixer.music.load(DIRECTORY + current_file)
        print 'Playing: ', current_file
        pygame.mixer.music.play()
    except:
        print 'Could not play file: ', current_file

def speak(text):
    """
    Speak the TEXT value using espeak module
    """

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
    sleep(1)
    while True:
        playcount = 20
        play(FILES)
        while pygame.mixer.music.get_busy() == True and playcount:
            sleep(1)
            playcount -= 1
        
