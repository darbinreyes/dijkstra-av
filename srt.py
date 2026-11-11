#!/usr/bin/python3

def make_template():
	"""
	Creates a file named init.srt with N subtitle lines that serve as a template
	"""
	f = open("init.srt", "w")

	for i in range(200):
		f.write("{}\n{}\n\n\n".format(i+1,"00:00:00,001 --> 00:00:00,000"))

	f.close()

def srt_add():

def main():
	print("Honestly, nevermind.")

if __name__ == "__main__":
	main()