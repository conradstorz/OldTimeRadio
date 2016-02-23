import os
import sys
import random
import pygame

def play(directory):

    file = random.choice(os.listdir(directory))
    pygame.init()
    pygame.mixer.init()
    pygame.mixer.music.load(directory + file)
    pygame.mixer.music.play()

play('./recordings/OTRadio/')
while pygame.mixer.music.get_busy() == True:
    continue