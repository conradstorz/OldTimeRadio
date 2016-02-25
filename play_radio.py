from os import listdir
from time import sleep
from random import choice
import pygame

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


while True:
    playcount = 20
    play(FILES)
    while pygame.mixer.music.get_busy() == True and playcount:
        sleep(1)
        playcount -= 1
        
