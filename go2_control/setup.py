from setuptools import find_packages, setup

package_name = 'go2_control'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dsc-labs',
    maintainer_email='dsclabs.contact@gmail.com',
    description='Keyboard teleop for Unitree Go2 (publishes TwistStamped to /cmd_vel_joy)',
    license='BSD-3-Clause',
    entry_points={
        'console_scripts': [
            'keyboard_teleop = go2_control.keyboard_teleop:main',
        ],
    },
)
