#!/usr/bin/python3

ESC = '\033'
CSI = ESC + '['

def SGR(*params):
    return CSI + ';'.join(str(p) for p in params) + 'm'

dark, red, green, yellow, blue, purple, cyan, white = (SGR(n) for n in range(30, 38))
reset = SGR()
