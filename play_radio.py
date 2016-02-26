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

def play(files_list, commercial=False):

    def not_a_commercial(file_name):
        if 'commercial' in file_name.lower():
            return False
        return True

    current_file = choice(files_list)
    
    if commercial:
        while not_a_commercial(current_file):
            current_file = choice(files_list)
     
    try:
        pygame.mixer.music.load(DIRECTORY + current_file)
        print 'Playing: ', current_file
        pygame.mixer.music.play()
    except:
        print 'Could not play file: ', current_file
    return (current_file, commercial)

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
        playcount = 300
        current_file = play(FILES)
        print current_file
        while pygame.mixer.music.get_busy() == True and playcount:
            sleep(1)
            playcount -= 1
            print playcount,
        
        if current_file[1] == False:  # is this a commercial? (True is commercial)
            # pause current_file for a commercial break
            saved = current_file

            playcount = 0
            current_file = play(FILES, commercial=True)
            while pygame.mixer.music.get_busy():
                sleep(1) # wait for commercial to finish
                playcount += 1
                print playcount,

            current_file = play(saved[0]) # return to our previous program
            # this will not currently work because the logic is wrong       
        
