import cv2
import numpy as np
from paddleocr import TextRecognition


class GameDigitRecognizer:
    def __init__(self, model_dir, use_gpu=False):
        # 初始化 PP-OCRv4 超轻量模型（仅启用数字识别，禁用方向分类）
        self.ocr =  TextRecognition(model_name="PP-OCRv4_mobile_rec", model_dir=model_dir)


    def _judge_arrow_direction(self, arrow_roi):
        """
        轻量判断箭头方向：右为正（+1），左为负（-1）
        arrow_roi: 裁剪后的箭头区域灰度图
        """
        # 二值化（箭头与背景色差大，固定阈值即可）
        _, binary = cv2.threshold(arrow_roi, 127, 255, cv2.THRESH_BINARY)
        h, w = binary.shape

        # 统计左右两半的前景像素（箭头）占比
        left_pixels = np.sum(binary[:, :w // 2] == 255)
        right_pixels = np.sum(binary[:, w // 2:] == 255)

        return 1 if right_pixels > left_pixels else -1

    def predict(self, img_path):
        """
        完整预测流程
        img_path: 图片路径
        """
        img = cv2.imread(img_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1. 箭头方向判断（固定 ROI 裁剪，无需检测）
        direction = 0
        direction = self._judge_arrow_direction(gray)

        # 2. 数字识别（固定 ROI 裁剪后识别，或全图检测）
        digit_value = 0.0
            # 仅对数字 ROI 做识别（跳过检测，更快）
        result = self.ocr.predict(img, batch_size=1)

        # 解析识别结果（过滤非数字内容）
        res = []
        for recognition in result:
            recognition.print()
            recognition.save_to_img(save_path="../PaddleOCR/output/")
            recognition.save_to_json(save_path="../PaddleOCR/output/res.json")
            res.append(recognition)

        # 结合方向返回最终结果（如方向为负，数字取反）
        final_value = digit_value * direction if direction != 0 else digit_value
        total = {
            "digit_value": digit_value,
            "arrow_direction": "正(右)" if direction == 1 else "负(左)" if direction == -1 else "未检测",
            "final_value": final_value
        }
        print(total)
        return total


# ------------------- 示例调用 -------------------
if __name__ == "__main__":
    model = GameDigitRecognizer('E:\project\dandan_aim\PaddleOCR\pretrain_models\PP-OCRv4_mobile_rec')
    while True:
        img = input("输入路径")
        output = model.predict(img)
