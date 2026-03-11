# api/routes/license.py
import os
from fastapi import APIRouter, Depends
from api.auth import get_current_key

router = APIRouter()

LICENSE_KEY = os.getenv('KUBEPOCKET_LICENSE_KEY', '')


def _get_license():
    try:
        from licensing.license import verify_license
        return verify_license(LICENSE_KEY)
    except ImportError:
        from licensing.license import LicenseInfo
        return LicenseInfo(valid=True)


@router.get("", summary="Get current license info")
def get_license(api_key: str = Depends(get_current_key)):
    lic = _get_license()
    result = lic.to_dict()

    # Append trial warning to response if expired
    if lic.is_trial and lic.trial_expired:
        result["warning"] = (
            "Your 30-day free trial has expired. "
            "The system continues to operate normally. "
            "Upgrade to Pro for unlimited access."
        )

    return result


@router.get("/check/{feature}", summary="Check if a feature is available")
def check_feature(feature: str, api_key: str = Depends(get_current_key)):
    lic = _get_license()
    allowed, message = (True, "") if lic.has_feature(feature) else (
        False, f"Feature '{feature}' not available on {lic.tier} tier. Upgrade your license.")

    result = {
        "feature": feature,
        "allowed": allowed,
        "tier":    lic.tier,
        "message": message,
    }

    if lic.is_trial and lic.trial_expired:
        result["warning"] = (
            "Your 30-day free trial has expired. "
            "The system continues to operate normally. "
            "Upgrade to Pro for unlimited access."
        )

    return result
