import pytest
from bot.models import User

def test_effective_max_accounts():
    user = User()

    # Test with no referral bonus
    assert user.effective_max_accounts(10) == 10

    # Test with referral bonus
    user.referral_bonus_accounts = 5
    assert user.effective_max_accounts(10) == 15

    # Test with zero plan base limit
    assert user.effective_max_accounts(0) == 5

    # Test with negative referral bonus (though maybe not possible in real life, good for testing logic)
    user.referral_bonus_accounts = -2
    assert user.effective_max_accounts(10) == 8

    # Test where referral_bonus_accounts is explicitly None
    user.referral_bonus_accounts = None
    assert user.effective_max_accounts(10) == 10
