#!/opt/local/bin/python

import sys
import math


def gcd(a, b):

	if a < b:
		t = a
		a = b
		b = t

	print("a  b  gcd(a,b)");

	while a - b > 1:
		print("{}  {}  {}".format(a, b, math.gcd(a, b)))
		t = a - b
		if t < b:
			a = b
			b = t
		else:
			a = t

	if a - b == 1:
		print("1")
	else:
		print(b)

def main():
	if len(sys.argv) != 3:
		print("Two postive integers please {}".format(len(sys.argv)))
		return

	gcd(int(sys.argv[1]), int(sys.argv[2]))

if __name__ == "__main__":
	main()