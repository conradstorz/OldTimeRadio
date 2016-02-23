import os
import sys
from time import sleep
import random
import pygame

def play(directory):

    file = random.choice(os.listdir(directory))
    pygame.init()
    pygame.mixer.init()
    pygame.mixer.music.load(directory + file)
    pygame.mixer.music.play()

while True:
    playcount = 100
    play('./recordings/OTRadio/')
    while pygame.mixer.music.get_busy() == True and playcount:
        sleep(.1)
        playcount -= 1
        continue