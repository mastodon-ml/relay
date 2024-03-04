import multiprocessing

from relay.manage import main


if __name__ == '__main__':
	multiprocessing.freeze_support()
	main()
