import holidays
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

class MarketCalendar:
    def __init__(self, timezone="US/Eastern"):
        self.timezone = ZoneInfo(timezone)
        self.us_holidays = holidays.US()  # Initialize U.S. holidays

    def is_trading_day(self, date):
        """Check if a given date is a trading day (not a weekend or holiday)."""
        # Weekends: Saturday (5), Sunday (6)
        if date.weekday() >= 5:
            return False
        # Check for U.S. market holidays
        return date not in self.us_holidays

    def get_previous_trading_day(self, date):
        """Get the previous trading day before the given date."""
        previous_day = date - timedelta(days=1)
        while not self.is_trading_day(previous_day):
            previous_day -= timedelta(days=1)
        return previous_day

    def get_market_hours(self, date, market_open_hour=9, market_open_minute=30, market_close_hour=16, market_close_minute=0):
        """
        Get the market open and close times for a given date in UTC.
        Args:
            date: datetime.date or datetime.datetime object
            market_open_hour, market_open_minute: Market open time in Eastern Time (e.g., 9:30 AM)
            market_close_hour, market_close_minute: Market close time in Eastern Time (e.g., 4:00 PM)
        Returns:
            Tuple of (market_open_utc, market_close_utc) as datetime objects in UTC.
        """
        if isinstance(date, datetime):
            date = date.date()
        eastern_tz = self.timezone
        market_open_eastern = datetime(
            date.year, date.month, date.day,
            market_open_hour, market_open_minute, tzinfo=eastern_tz
        )
        market_close_eastern = datetime(
            date.year, date.month, date.day,
            market_close_hour, market_close_minute, tzinfo=eastern_tz
        )
        market_open_utc = market_open_eastern.astimezone(ZoneInfo("UTC"))
        market_close_utc = market_close_eastern.astimezone(ZoneInfo("UTC"))
        return market_open_utc, market_close_utc

    def is_market_open(self, current_time):
        """
        Check if the market is open at the given time.
        Args:
            current_time: datetime object with timezone (preferably in UTC)
        Returns:
            bool: True if the market is open, False otherwise
        """
        # Convert current time to Eastern Time
        current_time_eastern = current_time.astimezone(self.timezone)
        current_date = current_time_eastern.date()

        # Check if today is a trading day
        if not self.is_trading_day(current_date):
            return False

        # Get market hours for today
        market_open, market_close = self.get_market_hours(
            current_date,
            market_open_hour=9,
            market_open_minute=30,
            market_close_hour=16,
            market_close_minute=0
        )

        # Convert current time to UTC for comparison
        current_time_utc = current_time.astimezone(ZoneInfo("UTC"))

        # Check if current time is within market hours
        return market_open <= current_time_utc <= market_close