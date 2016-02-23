import os
import sys
import pygame

def play(directory):

    file = random.choice(os.listdir(directory))
	pygame.init()
	pygame.mixer.init()
	pygame.mixer.music.load(file)
	pygame.mixer.music.play()

play(./recordings/OTRadio/)