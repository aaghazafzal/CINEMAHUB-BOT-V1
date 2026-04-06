import pymongo
from info import DATABASE_URI, DATABASE_NAME
import logging
import datetime

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

myclient = pymongo.MongoClient(DATABASE_URI)
mydb = myclient[DATABASE_NAME]


class UserTracker:
    def __init__(self):
        self.user_collection = mydb["referusers"]     # tracks who already joined via referral
        self.refer_collection = mydb["refers"]         # tracks referrer's points
        self.trial_collection = mydb["free_trials"]    # tracks who already used free trial

    # ─── Invite tracking ───────────────────────────────────────────────
    def add_user(self, user_id):
        if not self.is_user_in_list(user_id):
            self.user_collection.insert_one({'user_id': user_id})

    def remove_user(self, user_id):
        self.user_collection.delete_one({'user_id': user_id})

    def is_user_in_list(self, user_id):
        return bool(self.user_collection.find_one({'user_id': user_id}))

    # ─── Points system (1 point per referral) ──────────────────────────
    def add_refer_points(self, user_id: int, points: int):
        self.refer_collection.update_one(
            {'user_id': user_id},
            {'$set': {'points': points}},
            upsert=True
        )

    def increment_refer_point(self, user_id: int):
        """Add exactly 1 point per referral"""
        current = self.get_refer_points(user_id)
        self.add_refer_points(user_id, current + 1)
        return current + 1

    def get_refer_points(self, user_id: int):
        user = self.refer_collection.find_one({'user_id': user_id})
        return user.get('points', 0) if user else 0

    def get_total_refers(self, user_id: int):
        """Total lifetime referrals (never resets)"""
        user = self.refer_collection.find_one({'user_id': user_id})
        return user.get('total_refers', 0) if user else 0

    def increment_total_refers(self, user_id: int):
        self.refer_collection.update_one(
            {'user_id': user_id},
            {'$inc': {'total_refers': 1}},
            upsert=True
        )

    def deduct_points(self, user_id: int, points: int):
        """Deduct points after claiming reward"""
        current = self.get_refer_points(user_id)
        new_points = max(0, current - points)
        self.add_refer_points(user_id, new_points)
        return new_points

    # ─── Free Trial tracking ────────────────────────────────────────────
    def has_used_trial(self, user_id: int) -> bool:
        return bool(self.trial_collection.find_one({'user_id': user_id}))

    def mark_trial_used(self, user_id: int):
        if not self.has_used_trial(user_id):
            self.trial_collection.insert_one({
                'user_id': user_id,
                'used_at': datetime.datetime.utcnow()
            })


referdb = UserTracker()