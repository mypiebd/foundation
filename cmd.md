# Remove old app
rm -rf app

# Clone your repository
git clone https://github.com/mypiebd/foundation.git

# Rename app
mv foundation app

# Enter app
cd app

# Create Python virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# Make sure Gunicorn exists
which gunicorn

# if not
pip install gunicorn

# Restart LMS
sudo systemctl restart lms

# Check status
sudo systemctl status lms

# Check logs if anything is wrong
sudo journalctl -u lms -n 50 --no-pager