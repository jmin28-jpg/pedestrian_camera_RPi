import configparser
import os
import shutil
import sys
from pathlib import Path
from PySide6.QtCore import QByteArray
from log import get_logger
import app_paths

logger = get_logger(__name__)

# [Commit CONFIG-SCHEMA] 설정 스키마 정의 (섹션, 키, 기본값, 설명)
CONFIG_SCHEMA = {
    'app': {
        'comment': '프로그램 기본 동작 설정',
        'items': [
            ('split_mode', 'auto', '분할 모드 (auto/1/4) - ※ 내부 관리용 (수정 비권장)'),
            ('last_camera_index', '0', '마지막 선택 카메라 인덱스 - ※ 내부 관리용 (수정 비권장)'),
            ('log_retention_days', '30', '로그 파일 보관 기간 (일)'),
            ('db_retention_days', '30', 'DB 데이터 보관 기간 (일)')
        ]
    },
    'window': {
        'comment': '창 위치/크기 저장',
        'items': [
            ('geometry', '', '창 위치/크기 정보 (Base64) - ※ 내부 관리용 (수정 비권장)')
        ]
    },
    'event': {
        'comment': '이벤트 수신 및 처리 설정',
        'items': [
            ('enable', 'true', '이벤트 수신 기능 사용 여부 (true/false)'),
            ('heartbeat', '60', 'Heartbeat 주기 (초) - ※ 내부/예약 설정 (현재 RPi 버전에서는 일부 미사용)'),
            ('connect_timeout', '5', '연결 타임아웃 (초) - ※ 내부/예약 설정 (현재 RPi 버전에서는 일부 미사용)'),
            ('read_timeout', '65', '수신 대기 타임아웃 (초) - ※ 내부/예약 설정 (현재 RPi 버전에서는 일부 미사용)'),
            ('backoff_min', '1', '재연결 최소 대기시간 (초) - ※ 내부/예약 설정 (현재 RPi 버전에서는 일부 미사용)'),
            ('backoff_max', '30', '재연결 최대 대기시간 (초) - ※ 내부/예약 설정 (현재 RPi 버전에서는 일부 미사용)'),
            ('cooldown_sec', '2', '이벤트 중복 수신 방지 쿨다운 (초)'),
            ('stay_cooldown_sec', '2', '체류 이벤트 알림 쿨다운 (초)'),
            ('stay_hold_ms', '10000', '체류 상태 유지 시간 (밀리초)'),
            ('log_load_limit', '200', 'UI에 표시할 최근 이벤트 개수')
        ]
    },
    'gpio': {
        'comment': 'GPIO 하드웨어 출력 설정',
        'items': [
            ('enable', 'true', 'GPIO 사용 여부 (true/false)'),
            ('pulse_ms', '250', '출력 펄스 지속 시간 (밀리초)'),
            ('pulse_count', '2', '이벤트 1건당 GPIO 출력 반복 횟수'),
            ('pulse_interval', '0.1', '반복 펄스 사이 대기 시간(초)'),
            ('retrigger_policy', 'extend', '중복 트리거 정책 (extend:시간연장, ignore:무시, restart:재시작)'),
            ('console_log', 'false', 'GPIO 동작 콘솔 출력 여부 (디버깅용)')
        ]
    },
    'monitor': {
        'comment': '모니터링 및 자동 정지 설정',
        'items': [
            ('idle_stop_enable', 'true', '사용자 부재 시 자동 모니터링 정지 사용 여부'),
            ('idle_stop_sec', '300', '부재 판단 시간 (초, 300=5분)')
        ]
    }
}

class ConfigManager:
    def __init__(self):
        app_paths.ensure_dirs()
        # [Commit CFG-2] Use user home config (Persistent)
        self.config_file = self._get_user_config_path()
        self._ensure_config_exists()
        
        self.config = configparser.ConfigParser()

    def _get_user_config_path(self):
        path = app_paths.get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _get_embedded_default_config(self):
        if getattr(sys, "_MEIPASS", None):
            p = Path(sys._MEIPASS) / "defaults" / "config.ini"
            if p.exists(): return p
        # dev fallback:
        return Path(__file__).resolve().parent / "config.ini"

    def _ensure_config_exists(self):
        src = self._get_embedded_default_config()

        # 1) 파일이 없으면 기본 복사
        if not self.config_file.exists():
            if src and src.exists():
                try:
                    shutil.copy2(src, self.config_file)
                    logger.info(f"[Config] Initialized user config from {src} to {self.config_file}")
                except Exception as e:
                    logger.error(f"[Config] Failed to copy default config: {e}")
            return

    def load_or_create(self):
        """설정 파일이 없으면 기본값을 생성하고, 있으면 로드합니다."""
        if not self.config_file.exists():
            self._create_default()
        else:
            self.config.read(str(self.config_file), encoding='utf-8')
            # 파일이 존재하더라도 필수 섹션이 누락되었을 수 있으므로 확인 및 생성
            self._create_default()
        return self.config

    def _create_default(self):
        """기본 설정 파일 생성 (필수 섹션만 생성)"""
        changed = False
        
        # CONFIG_SCHEMA를 순회하며 누락된 섹션/키 확인
        for section, data in CONFIG_SCHEMA.items():
            if not self.config.has_section(section):
                self.config.add_section(section)
                changed = True
            
            for key, default_val, desc in data['items']:
                if not self.config.has_option(section, key):
                    self.config.set(section, key, default_val)
                    changed = True
            
        if changed:
            self._save_to_file()

    def reload(self):
        """설정 파일을 다시 로드합니다."""
        self.config.read(str(self.config_file), encoding='utf-8')
        return self.config

    def get_gpio_config(self):
        """GPIO 설정 반환"""
        return {
            'enable': self.config.getboolean('gpio', 'enable', fallback=True),
            'pulse_ms': self.config.getint('gpio', 'pulse_ms', fallback=500),
            'pulse_count': self.config.getint('gpio', 'pulse_count', fallback=1),
            'pulse_interval': self.config.getfloat('gpio', 'pulse_interval', fallback=0.1),
            'retrigger_policy': self.config.get('gpio', 'retrigger_policy', fallback='extend'),
            'console_log': self.config.getboolean('gpio', 'console_log', fallback=False)
        }

    def save_window_geometry(self, geometry: QByteArray):
        """윈도우 Geometry(QByteArray)를 Base64 문자열로 변환하여 저장"""
        if not self.config.has_section('window'):
            self.config.add_section('window')
        
        # QByteArray -> Base64 String 변환
        b64_str = geometry.toBase64().data().decode('utf-8')
        self.config.set('window', 'geometry', b64_str)
        self._save_to_file()

    def get_window_geometry(self) -> QByteArray:
        """저장된 Base64 문자열을 QByteArray로 복원하여 반환"""
        if self.config.has_option('window', 'geometry'):
            b64_str = self.config.get('window', 'geometry')
            if b64_str:
                return QByteArray.fromBase64(b64_str.encode('utf-8'))
        return QByteArray()

    def save_app_state(self, last_index, split_mode):
        """앱 상태(마지막 카메라 인덱스, 분할 모드) 저장"""
        if not self.config.has_section('app'):
            self.config.add_section('app')
        self.config.set('app', 'last_camera_index', str(last_index))
        self.config.set('app', 'split_mode', str(split_mode))
        self._save_to_file()

    def _save_to_file(self):
        """설정을 파일로 저장 (주석 포함을 위해 수동 저장)"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            # 스키마 순서대로 섹션 작성
            for section, data in CONFIG_SCHEMA.items():
                f.write(f"; ========================================================\n")
                f.write(f"; [{section.upper()}] {data['comment']}\n")
                f.write(f"; ========================================================\n")
                f.write(f"[{section}]\n")
                
                for key, default_val, comment in data['items']:
                    # 현재 메모리에 있는 값을 가져오되, 없으면 스키마 기본값 사용
                    val = self.config.get(section, key, fallback=default_val)
                    if comment:
                        f.write(f"; {comment}\n")
                    f.write(f"{key} = {val}\n\n")
                f.write("\n")
