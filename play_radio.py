import os
import sys
import pygame

def play(directory):

    file = random.choice(os.listdir(directory))
	pygame.play(file) 