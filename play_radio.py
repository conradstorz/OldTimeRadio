from os import listdir
from time import sleep
from random import choice
import pygame

files = listdir(directory)

pygame.init()
pygame.mixer.init()
pygame.mixer.music.set_volume(1)

def play(directory):
    current_file = choice(files)
    try:
        pygame.mixer.music.load(directory + current_file)
        print 'Playing: ', current_file
        pygame.mixer.music.play()
    except:
        print 'Could not play file: ', current_file


while True:
    playcount = 20
    play('./recordings/OTRadio/')
    while pygame.mixer.music.get_busy() == True and playcount:
        sleep(1)
        playcount -= 1
        
