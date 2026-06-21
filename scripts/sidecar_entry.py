from multiprocessing import freeze_support

from adv_search_flights.cli import main


if __name__ == "__main__":
    freeze_support()
    main()
